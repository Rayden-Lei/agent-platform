import json
from typing import Any, Callable, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.db.models import Agent, ModelConfig, RunNode, Tool
from app.db.session import SessionLocal
from app.model_gateway.gateway import build_llm
from app.tools.executor import execute_tool


class WorkflowState(TypedDict, total=False):
    input: Any
    output: Any
    condition_result: bool
    steps: list


_SAFE_BUILTINS = {
    "str": str, "len": len, "int": int, "float": float, "bool": bool,
    "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
}


def _eval_condition(expr: str, state: WorkflowState) -> bool:
    ns = {"input": state.get("input"), "output": state.get("output"), **_SAFE_BUILTINS}
    try:
        return bool(eval(expr, {"__builtins__": {}}, ns))  # noqa: S307 内部表达式，受限命名空间
    except Exception:
        return False


def _start_node(run_id: int, node_id: str, node_type: str, state: WorkflowState) -> int:
    if not run_id:
        return 0
    db = SessionLocal()
    try:
        rn = RunNode(run_id=run_id, node_id=node_id, node_type=node_type, status="running",
                     input={"data": json.dumps(state.get("input") if state.get("input") is not None else state.get("output"), ensure_ascii=False, default=str)[:500]})
        db.add(rn)
        db.commit()
        db.refresh(rn)
        return rn.id
    finally:
        db.close()


def _finish_node(rn_id: int, status: str, output: Any = None, error: str = None) -> None:
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


def _make_agent_node(config: dict, run_id: int, node_id: str) -> Callable:
    agent_id = config.get("agent_id")

    async def run(state: WorkflowState) -> dict:
        rn_id = _start_node(run_id, node_id, "agent", state)
        db = SessionLocal()
        try:
            agent = db.get(Agent, agent_id)
            if agent is None:
                out = {"output": f"智能体不存在: {agent_id}"}
                _finish_node(rn_id, "failed", out, "智能体不存在")
                return out
            model = db.get(ModelConfig, agent.model_id)
            llm = build_llm(model)
            text = str(state.get("output") if state.get("output") is not None else state.get("input", ""))
            resp = await llm.ainvoke([SystemMessage(content=agent.system_prompt), HumanMessage(content=text)])
            out = {"output": resp.content, "steps": [*state.get("steps", []), f"agent:{agent.name}"]}
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

    async def run(state: WorkflowState) -> dict:
        rn_id = _start_node(run_id, node_id, "tool", state)
        db = SessionLocal()
        try:
            tool_db = db.query(Tool).filter(Tool.name == tool_name).first()
            if tool_db is None:
                out = {"output": json.dumps({"error": f"工具不存在: {tool_name}"}, ensure_ascii=False)}
                _finish_node(rn_id, "failed", out, "工具不存在")
                return out
            raw = state.get("output") if state.get("output") is not None else state.get("input")
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
            result = await execute_tool(tool_db, args)
            out = {"output": json.dumps(result, ensure_ascii=False), "steps": [*state.get("steps", []), f"tool:{tool_name}"]}
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
        rn_id = _start_node(run_id, node_id, "condition", state)
        result = _eval_condition(expr, state)
        out = {"condition_result": result, "steps": [*state.get("steps", []), f"condition:{bool(result)}"]}
        _finish_node(rn_id, "success", out["condition_result"])
        return out

    return run


def _make_pass_node(config: dict, run_id: int, node_id: str) -> Callable:
    def run(state: WorkflowState) -> dict:
        _finish_node(_start_node(run_id, node_id, "pass", state), "success", None)
        return state
    return run


NODE_BUILDERS = {
    "start": _make_pass_node,
    "end": _make_pass_node,
    "agent": _make_agent_node,
    "tool": _make_tool_node,
    "condition": _make_condition_node,
}


def build_workflow(graph_data: dict, run_id: int = None):
    """把数据库 graph JSON（nodes/edges）编译成 LangGraph 可执行图。"""
    nodes = graph_data.get("nodes") or []
    edges = graph_data.get("edges") or []
    by_id = {n["id"]: n for n in nodes}

    g = StateGraph(WorkflowState)
    for n in nodes:
        builder = NODE_BUILDERS.get(n.get("type"), _make_pass_node)
        g.add_node(n["id"], builder(n.get("config") or {}, run_id, n["id"]))

    start_ids = [n["id"] for n in nodes if n.get("type") == "start"]
    end_ids = [n["id"] for n in nodes if n.get("type") == "end"]
    cond_ids = {n["id"] for n in nodes if n.get("type") == "condition"}

    cond_routes: dict[str, dict[str, str]] = {}
    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src in cond_ids:
            cond_routes.setdefault(src, {})[e.get("when", "true")] = dst

    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src in cond_ids:
            continue
        g.add_edge(src, dst)

    for cid, routes in cond_routes.items():
        mapping = {k: v for k, v in routes.items() if v in by_id}
        g.add_conditional_edges(cid, lambda s, _m=mapping: "true" if s.get("condition_result") else "false", mapping)

    for sid in start_ids:
        g.add_edge(START, sid)
    for eid in end_ids:
        g.add_edge(eid, END)

    return g.compile()
