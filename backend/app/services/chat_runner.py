"""对话执行器：一轮对话的流式执行，逐个产出统一的事件字典（citations / delta / tool_call / tool_result / done / error）。

路由只负责把事件转成 SSE 帧（docs/04 第 5 节）。登录对话、API Key 对话与分享访客走 stream_chat（访客的事件再经
share_service.guest_events 裁剪，docs/15 3.6），装配页调试走 stream_debug（docs/15 3.4，多出 prompt 与 trace 事件）；两者共用 _agent_events 这一个模型与工具循环，
所以执行逻辑不写在路由里（06 第 1 节：路由不写业务）。
调用前由 chat_service.prepare_chat / prepare_debug 建好运行记录：入参与归属类错误要在建流之前以 HTTP 状态码返回，不进事件流。
"""
import json
import logging
import time
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.prebuilt import create_react_agent
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.request_context import get_client_ip, get_request_id
from app.db.models import Run, User
from app.db.session import SessionLocal
from app.model_gateway.gateway import guarded_astream
from app.services import chat_service, chat_trace

warnings.filterwarnings("ignore", message=".*create_react_agent.*")
logger = logging.getLogger(__name__)

TOOL_RESULT_PREVIEW_CHARS = 200  # 工具结果下发与落库的截断长度
DEBUG_TOOL_RESULT_CHARS = 4000  # 调试放宽，便于看完整结果（docs/15 3.4）
PROMPT_EVENT_MAX_CHARS = 20000  # prompt 事件里的系统提示词截断长度（含注入的参考片段）


@dataclass(frozen=True)
class ChatTurn:
    """一轮对话的执行参数；conversation_id / run_id / agent_version 由 prepare_chat 事先定好，构建上下文按同一版本取配置。"""

    agent_id: int
    user_id: int
    role: str | None  # 检索鉴权用的角色；分享的匿名访客为 None，只放行公开库（docs/15 3.6）
    message: str
    conversation_id: int
    run_id: int
    agent_version: int
    kb_scope: list | None = None  # API Key 对话时为 Key 的 kb_ids，检索按 Key 的范围放行（docs/15 3.7.1）；登录对话为 None
    allow_http_tools: bool = True  # 分享访客按分享配置（默认不装配 HTTP 工具，docs/15 3.6）


class ToolRoundsExceeded(Exception):
    """本轮工具调用超过 TOOL_CALL_MAX_ROUNDS。文案是给用户看的，原样下发。"""

    def __init__(self, max_rounds: int):
        self.max_rounds = max_rounds
        super().__init__(f"超过最大工具调用轮数（{max_rounds}），已停止")


def _tool_round_guard(max_rounds: int):
    """post_model_hook：模型每次返回后数本轮已请求工具的次数，超过上限直接抛错，运行记录按失败收尾。

    不能只靠 recursion_limit：预置 react 智能体在剩余步数不足时会自己回一句英文 "Sorry, need more steps..." 正常结束，
    上层会把它当成功回答下发（langgraph 1.2.11 chat_agent_executor._are_more_steps_needed）。
    历史消息只有文本（chat_service._history_to_messages），state 里带 tool_calls 的 AIMessage 都是本轮产生的。
    """
    def guard(state) -> dict:
        rounds = sum(1 for m in state["messages"] if isinstance(m, AIMessage) and m.tool_calls)
        if rounds > max_rounds:
            raise ToolRoundsExceeded(max_rounds)
        return {}

    return guard


def _audit_retrieval(db, turn, ctx: chat_service.ChatContext, ip: str | None, source: str | None = None) -> None:
    """检索鉴权留痕：召回的 chunk_id、鉴权剔除数、重排方式。走 record_audit 才带得上来源 IP（2026-09-25 前直接写 AuditLog，ip 恒为空）。
    装配页调试的检索同样留痕（source=debug），调试也是一次真实的知识库访问。"""
    detail = {"query": turn.message, "recalled_chunk_ids": [c["chunk_id"] for c in ctx.citations],
              "acl_rejected": ctx.acl_rejected, "rerank_mode": ctx.rerank_mode}
    if source:
        detail["source"] = source
    record_audit(db, db.get(User, turn.user_id), "rag_retrieve", "agent", turn.agent_id, detail, ip)


def public_error(e: Exception) -> str:
    """下发给调用方的错误文案。BizError 与工具轮数超限本来就是写给用户看的，原样下发；
    其余一律固定文案 + trace_id —— 异常原文可能含内部地址或上游返回的整页 HTML，只进日志与运行记录。"""
    if isinstance(e, BizError):
        return e.detail
    if isinstance(e, ToolRoundsExceeded):
        return str(e)
    return f"生成失败，请稍后重试（trace: {get_request_id()}）"


@dataclass
class _StreamState:
    """一轮执行中累积的结果。用量按模型调用分开记再相加：一轮里有工具调用时模型会被调多次，
    2026-09-29 前每来一次用量就整体覆盖，只剩最后一次调用的 token，前几次的用量与成本都丢了。"""

    content: str = ""
    tool_calls: list = field(default_factory=list)
    usage_by_call: dict = field(default_factory=dict)
    first_token_ms: int | None = None

    def usage(self) -> dict:
        if not self.usage_by_call:
            return {}
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        return {k: sum(u.get(k, 0) for u in self.usage_by_call.values()) for k in keys}


class _LlmTrace:
    """调试时把每次模型调用、每次工具执行记成调用链步骤。模型调用以分块的 id 区分，第一个分块到达时开始，
    最后一个分块到达时结束；工具从模型调用结束时开始计时（工具节点跑完才一起返回，耗时是整个工具节点的）。"""

    def __init__(self, model):
        self.model = model
        self.call: dict | None = None
        self.next_clock = chat_trace.Clock()
        self.tool_clock: chat_trace.Clock | None = None

    def on_chunk(self, call_id: str, text: str, tool_names: list[str]) -> None:
        if self.call is None or self.call["id"] != call_id:
            self.call = {"id": call_id, "clock": self.next_clock, "chars": 0, "tools": [], "first_token_ms": None}
        call = self.call
        if text and call["first_token_ms"] is None:
            call["first_token_ms"] = call["clock"].elapsed_ms()
        call["chars"] += len(text)
        call["tools"].extend(n for n in tool_names if n)
        call["clock"].stop()

    def close_call(self, state: _StreamState) -> dict | None:
        call, self.call = self.call, None
        if call is None:
            return None
        self.tool_clock = call["clock"].successor()
        self.next_clock = chat_trace.Clock()
        return chat_trace.make_step("llm", self.model.name, call["clock"], output={"content_chars": call["chars"], "tool_calls": call["tools"]},
                                    meta={"model_id": self.model.id, "first_token_ms": call["first_token_ms"], "usage": state.usage_by_call.get(call["id"], {})})

    def tool_step(self, name: str, args, result: str) -> dict:
        try:
            parsed = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            parsed = None  # 工具返回的不是 JSON（纯文本结果，或被截断），按成功记
        failed = isinstance(parsed, dict) and "error" in parsed  # 执行器失败时返回 {"error": ...}，不抛异常
        clock = (self.tool_clock or chat_trace.Clock()).stop()
        self.next_clock = chat_trace.Clock()  # 下一次模型调用从工具结果回来时开始
        return chat_trace.make_step("tool", name, clock, input=args, output=result, status="error" if failed else "success")


async def _agent_events(ctx: chat_service.ChatContext, state: _StreamState, started: float, *, run_id: int,
                        tool_result_chars: int, trace: bool) -> AsyncIterator[dict]:
    """模型与工具循环：产出 delta / tool_call / tool_result（trace=True 时另产出 llm 与 tool 两类 trace 事件），结果累积进 state。
    异常原样抛出，由调用方按线上或调试各自收尾。"""
    max_rounds = settings.TOOL_CALL_MAX_ROUNDS
    graph = create_react_agent(ctx.llm, ctx.tools, prompt=ctx.system_prompt, post_model_hook=_tool_round_guard(max_rounds))
    # 工具参数按 (模型调用 id, 分块序号) 累积：每次模型调用的序号都从 0 开始，只按序号累积会把第二轮的参数拼到第一轮后面
    #（2026-09-29 前第二轮起的 tool_call 事件参数显示成 _raw 乱码；实际执行用的是模型解析好的参数，不受影响）
    tool_call_acc: dict[tuple, dict] = {}
    tool_call_by_id: dict[str, tuple] = {}
    tracer = _LlmTrace(ctx.model) if trace else None
    # 每轮工具调用走 agent → post_model_hook → tools 三步；上限留足余量，守卫先于它触发，它只兜底其他死循环
    config = {"recursion_limit": 3 * max_rounds + 10}
    # 熔断包装：打开期直接抛 503；首个 chunk 视为成功，建立流之前的异常计入失败
    stream = guarded_astream(ctx.model, graph.astream({"messages": ctx.history_messages}, config=config, stream_mode="messages"))
    async for chunk, _meta in stream:
        if isinstance(chunk, AIMessageChunk):
            call_id = chunk.id or "_"
            delta = chunk.content if isinstance(chunk.content, str) else ""
            if delta:
                if state.first_token_ms is None:
                    state.first_token_ms = int((time.perf_counter() - started) * 1000)
                state.content += delta
                yield {"type": "delta", "content": delta}
            for tc in getattr(chunk, "tool_call_chunks", None) or []:
                index = tc.get("index")
                if index is None:
                    continue
                entry = tool_call_acc.setdefault((call_id, index), {"name": "", "args_str": "", "id": ""})
                if tc.get("name"):
                    entry["name"] = tc["name"]
                if tc.get("id"):
                    entry["id"] = tc["id"]
                    tool_call_by_id[tc["id"]] = (call_id, index)
                entry["args_str"] += tc.get("args") or ""
            for tc in getattr(chunk, "tool_calls", None) or []:
                tc_id = tc.get("id")
                if tc_id and tc_id not in tool_call_by_id and (tc.get("args") or tc.get("name")):
                    yield {"type": "tool_call", "name": tc.get("name"), "arguments": tc.get("args", {}), "id": tc_id}
            um = getattr(chunk, "usage_metadata", None)
            if um:
                # 同一次调用内按最后一次为准（有的厂商在每个分块上给累计值），不同调用之间相加
                state.usage_by_call[call_id] = {"prompt_tokens": um.get("input_tokens", 0), "completion_tokens": um.get("output_tokens", 0),
                                                "total_tokens": um.get("total_tokens", 0)}
            if tracer:
                tracer.on_chunk(call_id, delta, [tc.get("name") for tc in (getattr(chunk, "tool_call_chunks", None) or [])])
        elif isinstance(chunk, ToolMessage):
            if tracer and (step := tracer.close_call(state)):
                yield {"type": "trace", "step": step}
            tc_id = chunk.tool_call_id
            key = tool_call_by_id.get(tc_id) if tc_id else None
            entry = tool_call_acc.get(key) if key is not None else None
            tool_name = "工具"
            args = {}
            if entry:
                tool_name = entry["name"] or "工具"
                if entry["args_str"]:
                    try:
                        args = json.loads(entry["args_str"])
                    except json.JSONDecodeError:
                        # 模型拼出的参数不是合法 JSON：原样透传给前端展示，不中断对话
                        logger.warning("工具调用参数不是合法 JSON run_id=%s tool=%s", run_id, entry["name"])
                        args = {"_raw": entry["args_str"]}
                yield {"type": "tool_call", "name": tool_name, "arguments": args, "id": tc_id or entry["id"]}
            result = str(chunk.content)[:tool_result_chars]
            state.tool_calls.append({"id": tc_id or (entry or {}).get("id"), "name": tool_name, "args": args, "result": result})
            yield {"type": "tool_result", "content": result, "tool_call_id": tc_id}
            if tracer:
                yield {"type": "trace", "step": tracer.tool_step(tool_name, args, result)}
    if tracer and (step := tracer.close_call(state)):
        yield {"type": "trace", "step": step}


async def stream_chat(turn: ChatTurn) -> AsyncIterator[dict]:
    """执行一轮线上对话并逐个产出事件。

    客户端中断（停止按钮 / 断网）时生成器被关闭，finally 收尾：已生成的部分回答落库、运行记录置 cancelled，
    避免运行记录永远停在 running。自己开数据库会话，路由请求结束后它还在用。
    """
    db = SessionLocal()
    state = _StreamState()
    citations: list = []
    finished = False  # 已正常收尾（done / failed）；finally 据此判断是否为客户端中断
    started = time.perf_counter()
    try:
        try:
            # 检索、历史装配要几百毫秒到几秒，放线程池，不拖住事件循环上的其他请求
            ctx = await run_in_threadpool(chat_service.build_chat_context, db, turn.agent_id, turn.message, turn.conversation_id,
                                          role=turn.role, agent_version=turn.agent_version, kb_scope=turn.kb_scope,
                                          allow_http_tools=turn.allow_http_tools)
        except Exception as e:
            if not isinstance(e, BizError):
                logger.exception("对话上下文构建失败 run_id=%s agent_id=%s", turn.run_id, turn.agent_id)
            chat_service.finalize_run(db, turn.run_id, "failed", error=e.detail if isinstance(e, BizError) else str(e))
            finished = True
            yield {"type": "error", "message": public_error(e)}
            return
        citations = ctx.citations
        # 来源 IP 在事件循环里取好再传进线程池，不依赖线程池是否复制请求上下文
        await run_in_threadpool(_audit_retrieval, db, turn, ctx, get_client_ip())
        yield {"type": "citations", "citations": citations}
        try:
            async for event in _agent_events(ctx, state, started, run_id=turn.run_id, tool_result_chars=TOOL_RESULT_PREVIEW_CHARS, trace=False):
                yield event
            usage = state.usage()
            assistant_msg = await run_in_threadpool(chat_service.save_assistant_message, db, turn.conversation_id, state.content, citations, usage,
                                                    state.tool_calls, turn.run_id)
            await run_in_threadpool(chat_service.finalize_run, db, turn.run_id, "success", content=state.content, usage=usage)
            finished = True
            logger.info("对话完成 run_id=%s 首字节 %sms 总 %dms", turn.run_id, state.first_token_ms if state.first_token_ms is not None else "-", int((time.perf_counter() - started) * 1000))
            yield {"type": "done", "message_id": assistant_msg.id, "run_id": turn.run_id, "conversation_id": turn.conversation_id, "usage": usage}
            if ctx.summary_pending:
                # 摘要压缩是一次完整的模型调用，放到响应之后的后台线程，下一轮对话用到新摘要
                chat_service.schedule_summary_refresh(ctx.model.id, turn.conversation_id)
        except Exception as e:
            _log_failure(e, turn.run_id, turn.agent_id)
            chat_service.finalize_run(db, turn.run_id, "failed", error=e.detail if isinstance(e, BizError) else str(e))
            finished = True
            yield {"type": "error", "message": public_error(e)}
    finally:
        if not finished:
            try:
                chat_service.finalize_cancelled_chat(db, turn.run_id, turn.conversation_id, state.content, citations, state.usage(), state.tool_calls)
            except Exception:
                logger.exception("对话中断收尾失败 run_id=%s", turn.run_id)
        db.close()


async def replay_chat(replay: chat_service.ReplayChat) -> AsyncIterator[dict]:
    """幂等回放（docs/15 3.7.1）：同一会话里重复的 client_message_id 不落消息、不调模型，按首次的结果下发同样的事件形状——
    首次完成：citations（有的话）+ 一条 delta 带回答全文 + done（首次的 message_id / run_id，replayed=true）；
    首次失败或中断：一条 error 带首次的错误文案。首次仍在生成的在 prepare_chat 就 409 了，到不了这里。"""
    if replay.status != "success":
        yield {"type": "error", "message": replay.error}
        return
    if replay.citations:
        yield {"type": "citations", "citations": replay.citations}
    yield {"type": "delta", "content": replay.content}
    yield {"type": "done", "message_id": replay.message_id, "run_id": replay.run_id, "conversation_id": replay.conversation_id,
           "usage": replay.usage, "replayed": True}


def _log_failure(e: Exception, run_id: int, agent_id: int) -> None:
    if isinstance(e, (BizError, ToolRoundsExceeded)):
        logger.warning("对话以业务错误结束 run_id=%s agent_id=%s：%s", run_id, agent_id, e)
    else:
        logger.exception("对话生成失败 run_id=%s agent_id=%s", run_id, agent_id)


async def stream_debug(turn: chat_service.DebugTurn) -> AsyncIterator[dict]:
    """装配页调试（docs/15 3.4，FR-041）：与线上同一个模型与工具循环，多下发实际系统提示词（prompt）与调用链（trace），
    done 带首字 / 总耗时 / 检索耗时 / 成本。不建会话、不落消息；运行记录 source=debug，中断时置 cancelled。"""
    db = SessionLocal()
    state = _StreamState()
    finished = False
    started = time.perf_counter()
    try:
        try:
            ctx = await run_in_threadpool(chat_service.build_debug_context, db, turn)
            await run_in_threadpool(_audit_retrieval, db, turn, ctx, get_client_ip(), "debug")
            yield {"type": "prompt", "system_prompt": ctx.system_prompt[:PROMPT_EVENT_MAX_CHARS], "history_count": len(ctx.history_messages) - 1}
            yield {"type": "citations", "citations": ctx.citations}
            for step in ctx.trace:
                yield {"type": "trace", "step": step}
            async for event in _agent_events(ctx, state, started, run_id=turn.run_id, tool_result_chars=DEBUG_TOOL_RESULT_CHARS, trace=True):
                yield event
        except Exception as e:
            _log_failure(e, turn.run_id, turn.agent_id)
            chat_service.finalize_run(db, turn.run_id, "failed", content=state.content or None, usage=state.usage() or None,
                                      error=e.detail if isinstance(e, BizError) else str(e))
            finished = True
            yield {"type": "error", "message": public_error(e)}
            return
        usage = state.usage()
        await run_in_threadpool(chat_service.finalize_run, db, turn.run_id, "success", content=state.content, usage=usage)
        finished = True
        run = db.get(Run, turn.run_id)
        metrics = {"first_token_ms": state.first_token_ms, "latency_ms": int((time.perf_counter() - started) * 1000), "retrieval_ms": ctx.retrieval_ms,
                   "cost": run.cost if run else None, "model_id": ctx.model.id, "model_name": ctx.model.name, "config_source": turn.config_source}
        yield {"type": "done", "run_id": turn.run_id, "usage": usage, "metrics": metrics}
    finally:
        if not finished:
            try:
                chat_service.finalize_run(db, turn.run_id, "cancelled", content=state.content, usage=state.usage() or None)
            except Exception:
                logger.exception("调试中断收尾失败 run_id=%s", turn.run_id)
        db.close()
