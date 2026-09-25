"""对话执行器：一轮对话的流式执行，逐个产出统一的事件字典（citations / delta / tool_call / tool_result / done / error）。

路由只负责把事件转成 SSE 帧（docs/04 第 5 节）。登录对话与 API Key 对话共用它，装配页调试、分享访客也将走它（docs/15 1B、1C），
所以执行逻辑不写在路由里（06 第 1 节：路由不写业务）。
调用前由 chat_service.prepare_chat 落好用户消息与运行记录：入参与归属类错误要在建流之前以 HTTP 状态码返回，不进事件流。
"""
import json
import logging
import time
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.prebuilt import create_react_agent
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.request_context import get_client_ip, get_request_id
from app.db.models import User
from app.db.session import SessionLocal
from app.model_gateway.gateway import guarded_astream
from app.services import chat_service

warnings.filterwarnings("ignore", message=".*create_react_agent.*")
logger = logging.getLogger(__name__)

TOOL_RESULT_PREVIEW_CHARS = 200  # 工具结果下发与落库的截断长度


@dataclass(frozen=True)
class ChatTurn:
    """一轮对话的执行参数；conversation_id / run_id 由 prepare_chat 事先建好。"""

    agent_id: int
    user_id: int
    role: str
    message: str
    conversation_id: int
    run_id: int


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


def _audit_retrieval(db, turn: ChatTurn, ctx: chat_service.ChatContext, ip: str | None) -> None:
    """检索鉴权留痕：召回的 chunk_id、鉴权剔除数、重排方式。走 record_audit 才带得上来源 IP（2026-09-25 前直接写 AuditLog，ip 恒为空）。"""
    detail = {"query": turn.message, "recalled_chunk_ids": [c["chunk_id"] for c in ctx.citations],
              "acl_rejected": ctx.acl_rejected, "rerank_mode": ctx.rerank_mode}
    record_audit(db, db.get(User, turn.user_id), "rag_retrieve", "agent", turn.agent_id, detail, ip)


def public_error(e: Exception) -> str:
    """下发给调用方的错误文案。BizError 与工具轮数超限本来就是写给用户看的，原样下发；
    其余一律固定文案 + trace_id —— 异常原文可能含内部地址或上游返回的整页 HTML，只进日志与运行记录。"""
    if isinstance(e, BizError):
        return e.detail
    if isinstance(e, ToolRoundsExceeded):
        return str(e)
    return f"生成失败，请稍后重试（trace: {get_request_id()}）"


async def stream_chat(turn: ChatTurn) -> AsyncIterator[dict]:
    """执行一轮对话并逐个产出事件。

    客户端中断（停止按钮 / 断网）时生成器被关闭，finally 收尾：已生成的部分回答落库、运行记录置 cancelled，
    避免运行记录永远停在 running。自己开数据库会话，路由请求结束后它还在用。
    """
    db = SessionLocal()
    final_content = ""
    usage_total: dict = {}
    tool_calls_list: list = []
    citations: list = []
    finished = False  # 已正常收尾（done / failed）；finally 据此判断是否为客户端中断
    started = time.perf_counter()
    first_token_ms: int | None = None
    try:
        try:
            # 检索、历史装配要几百毫秒到几秒，放线程池，不拖住事件循环上的其他请求
            ctx = await run_in_threadpool(chat_service.build_chat_context, db, turn.agent_id, turn.message, turn.conversation_id, role=turn.role)
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

        max_rounds = settings.TOOL_CALL_MAX_ROUNDS
        graph = create_react_agent(ctx.llm, ctx.tools, prompt=ctx.system_prompt, post_model_hook=_tool_round_guard(max_rounds))
        tool_call_acc: dict[int, dict] = {}
        tool_call_by_id: dict[str, int] = {}
        try:
            # 每轮工具调用走 agent → post_model_hook → tools 三步；上限留足余量，守卫先于它触发，它只兜底其他死循环
            config = {"recursion_limit": 3 * max_rounds + 10}
            # 熔断包装：打开期直接以 error 事件结束；首个 chunk 视为成功，建立流之前的异常计入失败
            stream = guarded_astream(ctx.model, graph.astream({"messages": ctx.history_messages}, config=config, stream_mode="messages"))
            async for chunk, _meta in stream:
                if isinstance(chunk, AIMessageChunk):
                    delta = chunk.content
                    if isinstance(delta, str) and delta:
                        if first_token_ms is None:
                            first_token_ms = int((time.perf_counter() - started) * 1000)
                        final_content += delta
                        yield {"type": "delta", "content": delta}
                    for tc in getattr(chunk, "tool_call_chunks", None) or []:
                        index = tc.get("index")
                        if index is None:
                            continue
                        entry = tool_call_acc.setdefault(index, {"name": "", "args_str": "", "id": ""})
                        if tc.get("name"):
                            entry["name"] = tc["name"]
                        if tc.get("id"):
                            entry["id"] = tc["id"]
                            tool_call_by_id[tc["id"]] = index
                        entry["args_str"] += tc.get("args") or ""
                    for tc in getattr(chunk, "tool_calls", None) or []:
                        tc_id = tc.get("id")
                        if tc_id and tc_id not in tool_call_by_id and (tc.get("args") or tc.get("name")):
                            yield {"type": "tool_call", "name": tc.get("name"), "arguments": tc.get("args", {}), "id": tc_id}
                    um = getattr(chunk, "usage_metadata", None)
                    if um:
                        usage_total = {
                            "prompt_tokens": um.get("input_tokens", 0),
                            "completion_tokens": um.get("output_tokens", 0),
                            "total_tokens": um.get("total_tokens", 0),
                        }
                elif isinstance(chunk, ToolMessage):
                    tc_id = chunk.tool_call_id
                    index = tool_call_by_id.get(tc_id) if tc_id else None
                    entry = tool_call_acc.get(index) if index is not None else None
                    tool_name = "工具"
                    args = {}
                    if entry:
                        tool_name = entry["name"] or "工具"
                        if entry["args_str"]:
                            try:
                                args = json.loads(entry["args_str"])
                            except json.JSONDecodeError:
                                # 模型拼出的参数不是合法 JSON：原样透传给前端展示，不中断对话
                                logger.warning("工具调用参数不是合法 JSON run_id=%s tool=%s", turn.run_id, entry["name"])
                                args = {"_raw": entry["args_str"]}
                        yield {"type": "tool_call", "name": tool_name, "arguments": args, "id": tc_id or entry["id"]}
                    result = str(chunk.content)[:TOOL_RESULT_PREVIEW_CHARS]
                    tool_calls_list.append({"id": tc_id or (entry or {}).get("id"), "name": tool_name, "args": args, "result": result})
                    yield {"type": "tool_result", "content": result, "tool_call_id": tc_id}

            assistant_msg = await run_in_threadpool(chat_service.save_assistant_message, db, turn.conversation_id, final_content, citations, usage_total, tool_calls_list)
            await run_in_threadpool(chat_service.finalize_run, db, turn.run_id, "success", content=final_content, usage=usage_total)
            finished = True
            logger.info("对话完成 run_id=%s 首字节 %sms 总 %dms", turn.run_id, first_token_ms if first_token_ms is not None else "-", int((time.perf_counter() - started) * 1000))
            yield {"type": "done", "message_id": assistant_msg.id, "run_id": turn.run_id, "conversation_id": turn.conversation_id, "usage": usage_total}
            if ctx.summary_pending:
                # 摘要压缩是一次完整的模型调用，放到响应之后的后台线程，下一轮对话用到新摘要
                chat_service.schedule_summary_refresh(ctx.model.id, turn.conversation_id)
        except Exception as e:
            if isinstance(e, (BizError, ToolRoundsExceeded)):
                logger.warning("对话以业务错误结束 run_id=%s agent_id=%s：%s", turn.run_id, turn.agent_id, e)
            else:
                logger.exception("对话生成失败 run_id=%s agent_id=%s", turn.run_id, turn.agent_id)
            chat_service.finalize_run(db, turn.run_id, "failed", error=e.detail if isinstance(e, BizError) else str(e))
            finished = True
            yield {"type": "error", "message": public_error(e)}
    finally:
        if not finished:
            try:
                chat_service.finalize_cancelled_chat(db, turn.run_id, turn.conversation_id, final_content, citations, usage_total, tool_calls_list)
            except Exception:
                logger.exception("对话中断收尾失败 run_id=%s", turn.run_id)
        db.close()
