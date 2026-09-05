import asyncio
import json
import logging
import operator
from typing import Annotated, Any, Callable, TypedDict

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.exceptions import BizError
from app.db.models import Agent, ModelConfig, RunNode, Tool
from app.db.session import SessionLocal
from app.model_gateway.gateway import build_llm, guarded_invoke
from app.rag.retriever import retrieve
from app.tools.executor import execute_tool
from app.tools.schema import check_tool_args
from app.workflow.validation import branch_predecessors, join_predecessors, validate_graph

logger = logging.getLogger(__name__)


def _merge_dict(current: dict, update: dict) -> dict:
    return {**(current or {}), **(update or {})}


def _last_write(current: Any, update: Any) -> Any:
    return update


class WorkflowState(TypedDict, total=False):
    """图状态。节点只返回增量，由 reducer 合并：steps 追加、node_outputs 合并、output 取最后一次写入。

    没有 reducer 的键在同一超步被两个节点写入会抛 InvalidUpdateError，并行分支（FR-029）靠这三个 reducer 才能跑；
    串行图下合并结果与"整体覆盖"完全相同。其余键只有单个写者，保持普通覆盖。
    """

    input: Any
    output: Annotated[Any, _last_write]
    condition_result: bool
    loop_index: int
    review_result: str
    node_outputs: Annotated[dict, _merge_dict]
    steps: Annotated[list, operator.add]


# 条件表达式可用的内置函数白名单：收窄 eval 的能力面，杜绝 import/open 等危险内置
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
    except Exception as e:
        # 表达式写错时按 false 走，但必须留日志：否则条件分支永远走 false 分支且无人知道原因
        logger.warning("条件表达式求值失败，按 false 处理：expr=%r error=%s", expr, e)
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


def _node_failed(rn_id: int, run_id: int, node_id: str, node_type: str, exc: Exception) -> None:
    """节点失败的统一收尾：写 failed 节点日志 + 带堆栈的错误日志。

    调用后必须 raise，让 workflow_service 把整条运行记录置为 failed；
    只写节点日志不抛异常会得到"节点失败但运行成功"的自相矛盾记录。
    """
    _finish_node(rn_id, "failed", error=str(exc))
    logger.exception("工作流节点执行失败 run_id=%s node_id=%s type=%s", run_id, node_id, node_type)


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
            except json.JSONDecodeError:
                # 上游输出不是 JSON，取不到字段属预期内情况（如取纯文本的 .code），不打日志避免刷屏
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


def _get_node_input(state: WorkflowState, config: dict, default_ref: str | None = None) -> Any:
    """按 config.input_ref 解析节点输入；未指定时取 default_ref 指向的节点输出（并行分支内由编译期给出前驱），
    再退到上一节点 output，最后回退 input。"""
    ref = (config or {}).get("input_ref")
    if ref:
        return _resolve_ref(state, ref)
    if default_ref:
        return (state.get("node_outputs") or {}).get(default_ref)
    return state.get("output") if state.get("output") is not None else state.get("input")


def _finalize_node_output(node_id: str, raw_output: Any, config: dict) -> dict:
    """按 config.output_field 提取字段，返回写入 output 与 node_outputs 的增量（由 reducer 合并进 state）。"""
    out = _extract_field(raw_output, (config or {}).get("output_field"))
    return {"output": out, "node_outputs": {node_id: out}}


def _make_agent_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """Agent 节点工厂：按 config.agent_id 查智能体，用其 system_prompt（可被 config.prompt 覆盖）调 LLM。

    节点函数签名 (state) -> dict；agent 不存在时写 failed 节点日志并返回错误文案，
    其他异常经 _node_failed 记录后重新抛出，由上层把整条运行置为 failed。
    default_ref（所有工厂同义）：并行分支内由编译期给出的前驱节点 id，未配 input_ref 时默认取它的输出。
    """
    agent_id = config.get("agent_id")
    prompt_override = config.get("prompt")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
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
            # 经熔断包装：打开期直接抛 503，节点按失败收尾，错误文本含"熔断中"
            resp = guarded_invoke(model, llm, [
                SystemMessage(content=prompt_override or agent.system_prompt),
                HumanMessage(content=str(input_val)),
            ])
            out = _finalize_node_output(node_id, resp.content, config)
            out["steps"] = [f"agent:{agent.name}"]
            _finish_node(rn_id, "success", out["output"])
            return out
        except Exception as e:
            _node_failed(rn_id, run_id, node_id, "agent", e)
            raise
        finally:
            db.close()

    return run


def _make_tool_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """工具节点工厂：按 config.tool_name 查工具；配了固定 args 用固定参数，否则把输入按 JSON 解析为参数。

    工具执行是异步的（execute_tool），而 LangGraph 节点是同步函数，这里用 asyncio.run 桥接；
    当前调用路径是同步 invoke，若未来在已有事件循环里运行本图会报错，需换桥接方式。
    """
    tool_name = config.get("tool_name")
    fixed_args = config.get("args")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
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
            # HTTP 工具按参数声明校验（FR-030）：不合法抛 ValueError → 节点 failed，错误文本"参数校验失败：..."
            args = check_tool_args(tool_db, args)
            result = asyncio.run(execute_tool(tool_db, args))
            out = _finalize_node_output(node_id, result, config)
            out["steps"] = [f"tool:{tool_name}"]
            _finish_node(rn_id, "success", out["output"])
            return out
        except Exception as e:
            _node_failed(rn_id, run_id, node_id, "tool", e)
            raise
        finally:
            db.close()

    return run


def _make_condition_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """条件节点工厂：对 config.expression 求值，结果写进 state.condition_result 供条件边路由。

    表达式异常按 false 处理（见 _eval_condition），因此上游字段拼写错误时，
    条件分支会静默走 false 分支，排查时靠 warning 日志定位。
    """
    expr = config.get("expression", "")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
        rn_id = _start_node(run_id, node_id, "condition", input_val)
        result = _eval_condition(expr, state)
        out = {"condition_result": result, "steps": [f"condition:{bool(result)}"]}
        _finish_node(rn_id, "success", result)
        return out

    return run


def _make_kb_node(config: dict, run_id: int, node_id: str, role: str = None, default_ref: str | None = None) -> Callable:
    """知识库检索节点工厂：按 config.kb_id/top_k 调用 retrieve，检索结果作为节点输出。

    role 用于检索层的权限过滤（与 retriever 的 ACL 两道闸门一致），
    由 build_workflow 在编译时从运行上下文带入，保证非 admin 触发者只能召回可见 chunk。
    """
    kb_id = config.get("kb_id")
    top_k = config.get("top_k")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
        rn_id = _start_node(run_id, node_id, "kb_retrieval", input_val)
        try:
            results = retrieve(kb_id, str(input_val), top_k, role=role)
            out = _finalize_node_output(node_id, results, config)
            out["steps"] = [f"kb_retrieval:{len(results)}"]
            _finish_node(rn_id, "success", json.dumps(out["output"], ensure_ascii=False))
            return out
        except Exception as e:
            _node_failed(rn_id, run_id, node_id, "kb_retrieval", e)
            raise

    return run


def _make_code_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """代码节点工厂：在受限命名空间里 exec 用户配置的代码，取 result（缺省用 output）作为节点输出。

    注意：这里放行完整 __builtins__（区别于条件表达式的白名单），属设计内的高风险能力，
    只应授权给可信工作流使用；异常统一走失败分支并留堆栈。
    """
    code = config.get("code", "")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
        rn_id = _start_node(run_id, node_id, "code", input_val)
        try:
            namespace = {"input": input_val, "output": input_val, "result": None}
            exec(code, {"__builtins__": __builtins__}, namespace)
            raw = namespace.get("result") if namespace.get("result") is not None else namespace.get("output", "")
            out = _finalize_node_output(node_id, raw, config)
            out["steps"] = ["code"]
            _finish_node(rn_id, "success", out["output"])
            return out
        except Exception as e:
            _node_failed(rn_id, run_id, node_id, "code", e)
            raise

    return run


def _make_http_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """HTTP 节点工厂：按 config.url/method 调用外部接口（GET 参数走 query，其余走 JSON body）。

    30 秒超时；非 2xx 响应 raise_for_status 抛异常走失败分支；响应按纯文本返回，
    需要结构化取数时配合节点的 output_field 提取。
    """
    url = config.get("url")
    method = config.get("method", "POST")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
        rn_id = _start_node(run_id, node_id, "http", input_val)
        try:
            with httpx.Client(timeout=30) as client:
                if str(method).upper() == "GET":
                    resp = client.get(url, params={"input": input_val})
                else:
                    resp = client.post(url, json={"input": input_val})
                resp.raise_for_status()
                raw = resp.text
            out = _finalize_node_output(node_id, raw, config)
            out["steps"] = ["http"]
            _finish_node(rn_id, "success", out["output"])
            return out
        except Exception as e:
            _node_failed(rn_id, run_id, node_id, "http", e)
            raise

    return run


def _make_loop_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """循环节点：递增 loop_index。由 build_workflow 添加条件边决定回环(loop)还是退出(exit)。"""

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
        rn_id = _start_node(run_id, node_id, "loop", input_val)
        idx = (state.get("loop_index") or 0) + 1
        out = {"loop_index": idx, "steps": [f"loop:{idx}"]}
        _finish_node(rn_id, "success", idx)
        return out

    return run


def _make_review_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """人工审核节点：interrupt 暂停，等待外部 resume(approve/reject)。"""
    instruction = config.get("instruction", "请审核")

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
        rn_id = _start_node(run_id, node_id, "human_review", input_val)
        try:
            decision = interrupt({
                "node_id": node_id,
                "instruction": instruction,
                "data": input_val,
            })
        except GraphInterrupt:
            # 暂停不是失败：把 running 日志标记为等待审核，resume 时会另起一条成功日志。
            # 只捕获 GraphInterrupt，其他异常走下面的失败分支，否则真故障会被伪装成"等待审核"。
            _finish_node(rn_id, "awaiting_review", input_val)
            raise
        except Exception as e:
            _node_failed(rn_id, run_id, node_id, "human_review", e)
            raise
        decision_str = json.dumps(decision, ensure_ascii=False, default=str)
        out = _finalize_node_output(node_id, decision, config)
        out["review_result"] = decision_str
        out["steps"] = [f"human_review:{decision_str}"]
        _finish_node(rn_id, "success", decision_str)
        return out

    return run


def _make_start_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """开始节点工厂：不改状态，只落一条 start 节点日志。

    返回空增量而不是整个 state：steps 带 reducer，回传整个 state 会把已有轨迹再追加一遍。
    """

    def run(state: WorkflowState) -> dict:
        rn_id = _start_node(run_id, node_id, "start", state.get("input"))
        _finish_node(rn_id, "success", state.get("input"))
        return {}

    return run


def _make_end_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """结束节点工厂：不改状态，只落一条 end 节点日志（同 start，返回空增量）。"""

    def run(state: WorkflowState) -> dict:
        rn_id = _start_node(run_id, node_id, "end", state.get("output"))
        _finish_node(rn_id, "success", state.get("output"))
        return {}

    return run


def _make_parallel_node(config: dict, run_id: int, node_id: str, default_ref: str | None = None) -> Callable:
    """并行节点（FR-029）：把输入透传为输出，各分支首节点默认取它；扇出由 build_workflow 按出边连线完成。"""

    def run(state: WorkflowState) -> dict:
        input_val = _get_node_input(state, config, default_ref)
        rn_id = _start_node(run_id, node_id, "parallel", input_val)
        _finish_node(rn_id, "success", input_val)
        return {"output": input_val, "node_outputs": {node_id: input_val}, "steps": ["parallel"]}

    return run


def _make_join_node(config: dict, run_id: int, node_id: str, predecessors: list[str]) -> Callable:
    """汇聚节点（FR-029）：等全部分支完成后（build_workflow 用列表边连入），
    把各分支末节点的输出收集成 {末节点 id: 输出} 作为本节点输出，并覆盖 state.output，
    之后的节点默认输入即该字典；output_field 仍可用于从中提取字段。
    并行超步内各分支对 output 的写入顺序不确定，所以 join 一定要重写 output，不能依赖"最后一个分支"。
    """

    def run(state: WorkflowState) -> dict:
        outputs = state.get("node_outputs") or {}
        collected = {pid: outputs.get(pid) for pid in predecessors}
        rn_id = _start_node(run_id, node_id, "join", collected)
        out = _finalize_node_output(node_id, collected, config)
        out["steps"] = ["join"]
        _finish_node(rn_id, "success", out["output"])
        return out

    return run


# 节点类型 → 工厂函数映射；未知节点类型回退到 start 工厂，保证任何图都能编译
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
    "parallel": _make_parallel_node,
    # join 需要前驱列表，在 build_workflow 里单独构造
}


def build_workflow(graph_data: dict, run_id: int = None, role: str = None):
    """把数据库 graph JSON（nodes/edges）编译成 LangGraph 可执行图。

    图校验（并行 / 汇聚结构）在这里兜底：服务层保存与运行前已显式校验并返回 400，
    这里抛出的 BizError 只会被 execute_workflow 吞成 failed（定时任务等无调用方的路径）。
    """
    errors = validate_graph(graph_data)
    if errors:
        raise BizError(400, "图校验失败：" + "；".join(errors))
    nodes = graph_data.get("nodes") or []
    edges = graph_data.get("edges") or []
    by_id = {n["id"]: n for n in nodes}
    # 并行分支内节点的默认输入来源（分支首节点 → parallel，其余 → 本分支前驱）；分支外的节点没有，走 output 回退
    default_refs = branch_predecessors(graph_data)
    join_preds = join_predecessors(graph_data)

    g = StateGraph(WorkflowState)
    for n in nodes:
        ntype, nid, config = n.get("type"), n["id"], n.get("config") or {}
        if ntype == "kb_retrieval":
            # 知识库检索节点需要携带触发者角色做权限过滤
            g.add_node(nid, _make_kb_node(config, run_id, nid, role, default_ref=default_refs.get(nid)))
        elif ntype == "join":
            g.add_node(nid, _make_join_node(config, run_id, nid, join_preds.get(nid, [])))
        else:
            builder = NODE_BUILDERS.get(ntype, _make_start_node)
            g.add_node(nid, builder(config, run_id, nid, default_ref=default_refs.get(nid)))

    start_ids = [n["id"] for n in nodes if n.get("type") == "start"]
    end_ids = [n["id"] for n in nodes if n.get("type") == "end"]
    cond_ids = {n["id"] for n in nodes if n.get("type") == "condition"}
    loop_ids = {n["id"] for n in nodes if n.get("type") == "loop"}
    join_ids = set(join_preds)

    # 先把条件/循环节点的出边按 when 收集成路由映射；这两类节点的边不直接连，见下方条件边/循环边
    cond_routes: dict[str, dict[str, str]] = {}
    loop_routes: dict[str, dict[str, str]] = {}
    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src in cond_ids:
            # 条件边的 when 取值：true / false
            cond_routes.setdefault(src, {})[e.get("when", "true")] = dst
        elif src in loop_ids:
            # 循环边的 when 取值：loop（回环）/ exit（退出）
            loop_routes.setdefault(src, {})[e.get("when", "loop")] = dst

    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src in cond_ids or src in loop_ids:
            # 条件/循环节点的边已在上面收集，跳过以免重复连接
            continue
        if dst in join_ids:
            # 汇聚节点的入边下面按列表一次性连：逐条 add_edge 会让 join 在每条分支完成时各跑一次
            continue
        # parallel 的多条出边就是普通直连边：LangGraph 对同一节点的多条出边天然在下一超步并发执行
        g.add_edge(src, dst)

    for jid, preds in join_preds.items():
        # 列表边：等全部前驱（各分支末节点）完成后再执行 join
        g.add_edge(preds, jid)

    for cid, routes in cond_routes.items():
        # 条件边：按 state.condition_result 路由 true/false；映射里指向不存在节点的出口被过滤掉
        mapping = {k: v for k, v in routes.items() if v in by_id}
        g.add_conditional_edges(
            cid,
            # 用默认参数绑定 mapping：lambda 闭包延迟绑定，不绑的话所有条件边会共用最后一份 mapping
            lambda s, _m=mapping: "true" if s.get("condition_result") else "false",
            mapping,
        )

    for lid, routes in loop_routes.items():
        config = (by_id[lid].get("config") or {})
        count = int(config.get("count") or 1)
        expr = config.get("expression")
        mapping = {k: v for k, v in routes.items() if v in by_id}

        def _route(state: WorkflowState, _expr=expr, _count=count) -> str:
            # 循环边：配了 expression 按表达式决定回环/退出（表达式异常按 false 走 exit），
            # 否则按 loop_index 是否达到 count 决定；默认参数绑定同上，避免共享最后一次循环配置
            if _expr:
                return "loop" if _eval_condition(_expr, state) else "exit"
            return "loop" if (state.get("loop_index") or 0) < _count else "exit"

        g.add_conditional_edges(lid, _route, mapping)

    # 把 start/end 节点接到图的入口与出口；同类型多个时全部接入
    for sid in start_ids:
        g.add_edge(START, sid)
    for eid in end_ids:
        g.add_edge(eid, END)

    return g.compile(checkpointer=_checkpointer)
