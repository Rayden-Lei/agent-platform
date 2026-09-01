import asyncio
import json
from typing import Any, Callable, TypedDict

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.db.models import Agent, ModelConfig, RunNode, Tool
from app.db.session import SessionLocal
from app.model_gateway.gateway import build_llm
from app.rag.retriever import retrieve
from app.tools.executor import execute_tool


class WorkflowState(TypedDict, total=False):
    input: Any
    output: Any
    condition_result: bool
    loop_index: int
    review_result: str
    node_outputs: dict
    steps: list


_SAFE_BUILTINS = {
    "str": str, "len": len, "int": int, "float": float, "bool": bool,
    "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
}

# 进程内共享 checkpointer：run 与 resume 用同一个，才能恢复被 interrupt 的图。
# 内部使用场景下审核间隔通常不跨进程重启；如需跨进程请换 SqliteSaver。
_checkpointer = MemorySaver()


def _eval_condition(expr: str, state: WorkflowState) -> bool:
    ns = {
        "input": state.get("input"),
        "output": state.get("output"),
        "loop_index": state.get("loop_index"),
        "review_result": state.get("review_result"),
        **_SAFE_BUILTINS,
    }
    try:
        return bool(eval(expr, {"__builtins__": {}}, ns))  # noqa: S307 内部表达式，受限命名空间
    except Exception:
        return False


def _start_node(run_id: int, node_id: str, node_type: str, input_data: Any = None) -> int:
    """节点开始：写入 running 状态日志，返回 RunNode.id。每个节点都必须调用。"""
    if not run_id:
        return 0
    db = SessionLocal()
    try:
        rn = RunNode(
            run_id=run_id, node_id=node_id, node_type=node_type, status="running",
            input={"data": json.dumps(input_data, ensure_ascii=False, default=str)[:500]},
        )
        db.add(rn)
        db.commit()
        db.refresh(rn)
        return rn.id
    finally:
        db.close()


def _finish_node(rn_id: int, status: str, output: Any = None, error: str = None) -> None:
    """节点结束：写入 success/failed 状态与输出。每个节点都必须调用。"""
    if not rn_id:
        return
    db = SessionLocal()
    try:
        rn = db.get(RunNode, rn_id)
        if rn:
            rn.status = status
            if output is not None:
                rn.output = {"data": json.dumps(output, ensure_ascii=False, default=str)[:500]}
            if error:
                rn.error = str(error)[:1000]
            db.commit()
    finally:
        db.close()


def _extract_field(value: Any, field: str) -> Any:
    """按点路径从输出中提取字段，支持 dict/list/JSON 字符串。"""
    if not field:
        return value
    for p in str(field).split("."):
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(p)
        elif isinstance(value, (list, tuple)):
            try:
                value = value[int(p)]
            except (ValueError, IndexError):
                return None
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return None
            value = _extract_field(parsed, p)
        else:
            return None
    return value


def _resolve_ref(state: WorkflowState, ref: str) -> Any:
    """解析变量引用，支持 {{input}} / {{output}} / {{node_id}} / {{node_id.field.path}}。"""
    if not ref:
        return None
    ref = str(ref).strip()
    if ref.startswith("{{") and ref.endswith("}}"):
        ref = ref[2:-2].strip()
    if not ref:
        return None
    if ref == "input":
        return state.get("input")
    if ref == "output":
        return state.get("output")
    parts = ref.split(".")
    first = parts[0]
    if first == "input":
        value = state.get("input")
    elif first == "output":
        value = state.get("output")
    else:
        value = (state.get("node_outputs") or {}).get(first)
    return _extract_field(value, ".".join(parts[1:])) if len(parts) > 1 else value


def _get_node_input(state: WorkflowState, config: dict) -> Any:
    """按 config.input_ref 解析节点输入；未指定则取上一节点 output，再回退 input。"""
    ref = (config or {}).get("input_ref")
    if ref:
        return _resolve_ref(state, ref)
    return state.get("output") if state.get("output") is not None else state.get("input")


def _finalize_node_output(state: WorkflowState, node_id: str, raw_output: Any, config: dict) -> dict:
    """把节点输出写入 state.output，并按 config.output_field 提取字段，同时记录 node_outputs。"""
    out = _extract_field(raw_output, (config or {}).get("output_field"))
    node_outputs = {**(state.get("node_outputs") or {}), node_id: out}
    return {"output": out, "node_outputs": node_outputs}


def _make_agent_node(config: dict, run_id: int, node_id: str) -> Callable:
    agent_id = config.get("agent_id")
    prompt_override = config.get("prompt")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config)
        rn_id = _start_node(run_id, node_id, "agent", input_val)
        db = SessionLocal()
        try:
            agent = db.get(Agent, agent_id)
            if agent is None:
                out = {"output": f"智能体不存在: {agent_id}"}
                _finish_node(rn_id, "failed", out["output"], "智能体不存在")
                return out
            model = db.get(ModelConfig, agent.model_id)
            llm = build_llm(model)
            resp = llm.invoke([
                SystemMessage(content=prompt_override or agent.system_prompt),
                HumanMessage(content=str(input_val)),
            ])
            out = _finalize_node_output(state, node_id, resp.content, config)
            out["steps"] = [*state.get("steps", []), f"agent:{agent.name}"]
            _finish_node(rn_id, "success", out["output"])
            return out
        except Exception as e:
            _finish_node(rn_id, "failed", error=str(e))
            raise
        finally:
            db.close()

    return run


def _make_tool_node(config: dict, run_id: int, node_id: str) -> Callable:
    tool_name = config.get("tool_name")
    fixed_args = config.get("args")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config)
        rn_id = _start_node(run_id, node_id, "tool", input_val)
        db = SessionLocal()
        try:
            tool_db = db.query(Tool).filter(Tool.name == tool_name).first()
            if tool_db is None:
                out = {"output": json.dumps({"error": f"工具不存在: {tool_name}"}, ensure_ascii=False)}
                _finish_node(rn_id, "failed", out["output"], "工具不存在")
                return out
            if fixed_args:
                args = fixed_args
            else:
                args = json.loads(input_val) if isinstance(input_val, str) else (input_val or {})
            result = asyncio.run(execute_tool(tool_db, args))
            out = _finalize_node_output(state, node_id, result, config)
            out["steps"] = [*state.get("steps", []), f"tool:{tool_name}"]
            _finish_node(rn_id, "success", out["output"])
            return out
        except Exception as e:
            _finish_node(rn_id, "failed", error=str(e))
            raise
        finally:
            db.close()

    return run


def _make_condition_node(config: dict, run_id: int, node_id: str) -> Callable:
    expr = config.get("expression", "")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config)
        rn_id = _start_node(run_id, node_id, "condition", input_val)
        result = _eval_condition(expr, state)
        out = {"condition_result": result, "steps": [*state.get("steps", []), f"condition:{bool(result)}"]}
        _finish_node(rn_id, "success", result)
        return out

    return run


def _make_kb_node(config: dict, run_id: int, node_id: str, role: str = None) -> Callable:
    kb_id = config.get("kb_id")
    top_k = config.get("top_k")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config)
        rn_id = _start_node(run_id, node_id, "kb_retrieval", input_val)
        try:
            results = retrieve(kb_id, str(input_val), top_k, role=role)
            out = _finalize_node_output(state, node_id, results, config)
            out["steps"] = [*state.get("steps", []), f"kb_retrieval:{len(results)}"]
            _finish_node(rn_id, "success", json.dumps(out["output"], ensure_ascii=False))
            return out
        except Exception as e:
            _finish_node(rn_id, "failed", error=str(e))
            raise

    return run


def _make_code_node(config: dict, run_id: int, node_id: str) -> Callable:
    code = config.get("code", "")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config)
        rn_id = _start_node(run_id, node_id, "code", input_val)
        try:
            namespace = {"input": input_val, "output": input_val, "result": None}
            exec(code, {"__builtins__": __builtins__}, namespace)
            raw = namespace.get("result") if namespace.get("result") is not None else namespace.get("output", "")
            out = _finalize_node_output(state, node_id, raw, config)
            out["steps"] = [*state.get("steps", []), "code"]
            _finish_node(rn_id, "success", out["output"])
            return out
        except Exception as e:
            _finish_node(rn_id, "failed", error=str(e))
            raise

    return run


def _make_http_node(config: dict, run_id: int, node_id: str) -> Callable:
    url = config.get("url")
    method = config.get("method", "POST")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config)
        rn_id = _start_node(run_id, node_id, "http", input_val)
        try:
            with httpx.Client(timeout=30) as client:
                if str(method).upper() == "GET":
                    resp = client.get(url, params={"input": input_val})
                else:
                    resp = client.post(url, json={"input": input_val})
                resp.raise_for_status()
                raw = resp.text
            out = _finalize_node_output(state, node_id, raw, config)
            out["steps"] = [*state.get("steps", []), "http"]
            _finish_node(rn_id, "success", out["output"])
            return out
        except Exception as e:
            _finish_node(rn_id, "failed", error=str(e))
            raise

    return run


def _make_loop_node(config: dict, run_id: int, node_id: str) -> Callable:
    """循环节点：递增 loop_index。由 build_workflow 添加条件边决定回环(loop)还是退出(exit)。"""

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config)
        rn_id = _start_node(run_id, node_id, "loop", input_val)
        idx = (state.get("loop_index") or 0) + 1
        out = {"loop_index": idx, "steps": [*state.get("steps", []), f"loop:{idx}"]}
        _finish_node(rn_id, "success", idx)
        return out

    return run


def _make_review_node(config: dict, run_id: int, node_id: str) -> Callable:
    """人工审核节点：interrupt 暂停，等待外部 resume(approve/reject)。"""
    instruction = config.get("instruction", "请审核")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config)
        rn_id = _start_node(run_id, node_id, "human_review", input_val)
        try:
            decision = interrupt({
                "node_id": node_id,
                "instruction": instruction,
                "data": input_val,
            })
        except Exception:
            # interrupt 暂停：把 running 日志标记为等待审核，resume 时会另起一条成功日志
            _finish_node(rn_id, "awaiting_review", input_val)
            raise
        decision_str = json.dumps(decision, ensure_ascii=False, default=str)
        out = _finalize_node_output(state, node_id, decision, config)
        out["review_result"] = decision_str
        out["steps"] = [*state.get("steps", []), f"human_review:{decision_str}"]
        _finish_node(rn_id, "success", decision_str)
        return out

    return run


def _make_start_node(config: dict, run_id: int, node_id: str) -> Callable:
    def run(state: WorkflowState) -> dict:
        rn_id = _start_node(run_id, node_id, "start", state.get("input"))
        _finish_node(rn_id, "success", state.get("input"))
        return state

    return run


def _make_end_node(config: dict, run_id: int, node_id: str) -> Callable:
    def run(state: WorkflowState) -> dict:
        rn_id = _start_node(run_id, node_id, "end", state.get("output"))
        _finish_node(rn_id, "success", state.get("output"))
        return state

    return run


NODE_BUILDERS = {
    "start": _make_start_node,
    "end": _make_end_node,
    "agent": _make_agent_node,
    "tool": _make_tool_node,
    "condition": _make_condition_node,
    "kb_retrieval": _make_kb_node,
    "code": _make_code_node,
    "http": _make_http_node,
    "loop": _make_loop_node,
    "human_review": _make_review_node,
}


def build_workflow(graph_data: dict, run_id: int = None, role: str = None):
    """把数据库 graph JSON（nodes/edges）编译成 LangGraph 可执行图。"""
    nodes = graph_data.get("nodes") or []
    edges = graph_data.get("edges") or []
    by_id = {n["id"]: n for n in nodes}

    g = StateGraph(WorkflowState)
    for n in nodes:
        ntype = n.get("type")
        if ntype == "kb_retrieval":
            # 知识库检索节点需要携带触发者角色做权限过滤
            g.add_node(n["id"], _make_kb_node(n.get("config") or {}, run_id, n["id"], role))
        else:
            builder = NODE_BUILDERS.get(ntype, _make_start_node)
            g.add_node(n["id"], builder(n.get("config") or {}, run_id, n["id"]))

    start_ids = [n["id"] for n in nodes if n.get("type") == "start"]
    end_ids = [n["id"] for n in nodes if n.get("type") == "end"]
    cond_ids = {n["id"] for n in nodes if n.get("type") == "condition"}
    loop_ids = {n["id"] for n in nodes if n.get("type") == "loop"}

    cond_routes: dict[str, dict[str, str]] = {}
    loop_routes: dict[str, dict[str, str]] = {}
    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src in cond_ids:
            cond_routes.setdefault(src, {})[e.get("when", "true")] = dst
        elif src in loop_ids:
            loop_routes.setdefault(src, {})[e.get("when", "loop")] = dst

    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src in cond_ids or src in loop_ids:
            continue
        g.add_edge(src, dst)

    for cid, routes in cond_routes.items():
        mapping = {k: v for k, v in routes.items() if v in by_id}
        g.add_conditional_edges(
            cid,
            lambda s, _m=mapping: "true" if s.get("condition_result") else "false",
            mapping,
        )

    for lid, routes in loop_routes.items():
        config = (by_id[lid].get("config") or {})
        count = int(config.get("count") or 1)
        expr = config.get("expression")
        mapping = {k: v for k, v in routes.items() if v in by_id}

        def _route(state: WorkflowState, _expr=expr, _count=count) -> str:
            if _expr:
                return "loop" if _eval_condition(_expr, state) else "exit"
            return "loop" if (state.get("loop_index") or 0) < _count else "exit"

        g.add_conditional_edges(lid, _route, mapping)

    for sid in start_ids:
        g.add_edge(START, sid)
    for eid in end_ids:
        g.add_edge(eid, END)

    return g.compile(checkpointer=_checkpointer)
