import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import settings
from app.core.exceptions import BizError
from app.db.models import Agent, Conversation, Message, ModelConfig, Run, Tool
from app.db.session import SessionLocal
from app.model_gateway import breaker
from app.model_gateway.gateway import build_llm, guarded_invoke
from app.rag.retriever import retrieve, retrieve_with_stats
from app.services import run_service, settings_service
from app.tools.langchain_tools import build_tools

logger = logging.getLogger(__name__)


@dataclass
class ChatContext:
    """一次对话的完整上下文：模型配置（熔断按它计数）、LLM、工具、系统提示（含 RAG 引用）、多轮历史消息。"""

    model: ModelConfig
    llm: Any
    tools: list
    system_prompt: str
    citations: list
    history_messages: list
    acl_rejected: int = 0
    rerank_mode: str | None = None  # 本轮检索实际用的重排后端（model / lexical），写进审计
    summary_pending: bool = False  # 待折叠消息已攒够一批：响应结束后在后台刷新会话摘要，不占用本轮首字节


def _history_to_messages(rows: list) -> list:
    """DB 历史行 → langchain 消息列表（仅取 user/assistant）。"""
    msgs = []
    for h in rows:
        if h.role == "user":
            msgs.append(HumanMessage(content=h.content))
        elif h.role == "assistant":
            msgs.append(AIMessage(content=h.content))
    return msgs


# 摘要失败时待折叠消息退回原文注入的字符上限：摘要不可用也要保证注入的 token 有界
SUMMARY_FALLBACK_CHARS = 2000


def _plain_text(messages: list) -> str:
    return "\n".join(f"{m.type}: {m.content}" for m in messages)


def _summarize_history(model: ModelConfig, llm: Any, previous_summary: str, pending: list) -> str | None:
    """用 LLM 把"旧摘要 + 待折叠消息"压成一段新摘要；失败或为空返回 None，由调用方决定降级方式。

    熔断打开期间 guarded_invoke 直接抛 503，这里同样走降级不对外报错；失败照常计入该模型的连续失败。
    """
    prompt = (
        "你是对话摘要助手。请把下面的历史对话压缩成一段不超过 150 字的摘要，"
        "只保留用户目标、关键事实和已确认结论，不要编造信息。\n\n"
    )
    if previous_summary:
        prompt += "【更早对话的已有摘要】\n" + previous_summary + "\n\n【需要并入摘要的新对话】\n"
    prompt += _plain_text(pending)
    try:
        resp = guarded_invoke(model, llm, prompt)
        summary = (resp.content or "").strip() if resp else ""
    except Exception as e:
        # 摘要失败不影响对话，但这批历史会退化为字符截断，质量下降，必须能看见
        logger.warning("历史摘要生成失败，本轮待折叠消息退回字符截断：%s", e)
        return None
    return summary or None


def _split_history(conversation: Conversation, rows: list, max_messages: int) -> tuple[list, list, list]:
    """把会话消息切成 (待折叠的更早消息, 最近 max_messages 条, 已折叠摘要文本)。

    更早消息里 id 大于 summary_upto_message_id 的是"待折叠"（还没并进摘要）。
    """
    if len(rows) <= max_messages:
        return [], rows, conversation.summary or ""
    older_rows, recent_rows = rows[:-max_messages], rows[-max_messages:]
    upto = conversation.summary_upto_message_id or 0
    return [r for r in older_rows if r.id > upto], recent_rows, conversation.summary or ""


def _build_history_messages(conversation: Conversation, rows: list, max_messages: int) -> tuple[list, bool]:
    """有界历史（FR-031）：保留最近 max_messages 条原文，更早的用会话上持久化的摘要代替。返回 (消息列表, 是否需要后台刷新摘要)。

    本函数不调用模型（2026-09-06 起）：摘要生成是一次完整的模型调用，放在请求路径上会让首字节多等好几秒。
    待折叠消息不足一批时按原文注入；攒够 CHAT_SUMMARY_BATCH_MESSAGES 条时本轮先注入截断原文，
    并返回 summary_pending=True，由对话路由在响应结束后调用 refresh_conversation_summary 在后台压缩落库，下一轮生效。
    注入顺序：[摘要] + 未折叠的更早消息原文 + 最近 max_messages 条。
    """
    pending_rows, recent_rows, summary = _split_history(conversation, rows, max_messages)
    pending = _history_to_messages(pending_rows)
    needs_refresh = len(pending_rows) >= settings.CHAT_SUMMARY_BATCH_MESSAGES
    if needs_refresh:
        pending = [SystemMessage(content="以下是更早对话的原文节选（摘要更新中，已截断）：\n" + _plain_text(pending)[:SUMMARY_FALLBACK_CHARS])]
    messages = [SystemMessage(content="以下是更早对话的摘要（非逐字历史）：\n" + summary)] if summary else []
    return messages + pending + _history_to_messages(recent_rows), needs_refresh


def refresh_conversation_summary(db: Session, model: ModelConfig, llm: Any, conversation: Conversation, max_messages: int | None = None) -> bool:
    """把攒够一批的待折叠消息并进会话摘要并落库。返回是否更新了摘要。

    失败时旧摘要与边界不动（下一轮再试），截断文本不当摘要落库。既可由对话路由在响应后异步调用，也可直接调用（测试）。
    """
    max_messages = max_messages or settings.CHAT_HISTORY_MAX_MESSAGES
    rows = db.query(Message).filter(Message.conversation_id == conversation.id).order_by(Message.id).all()
    pending_rows, _, summary = _split_history(conversation, rows, max_messages)
    if len(pending_rows) < settings.CHAT_SUMMARY_BATCH_MESSAGES:
        return False
    new_summary = _summarize_history(model, llm, summary, _history_to_messages(pending_rows))
    if not new_summary:
        return False
    conversation.summary = new_summary
    conversation.summary_upto_message_id = pending_rows[-1].id
    conversation.summary_updated_at = datetime.now(timezone.utc)
    db.commit()
    return True


def schedule_summary_refresh(model_id: int, conversation_id: int) -> threading.Thread:
    """响应结束后在后台线程刷新摘要：自己开会话，失败只记日志。返回线程对象便于测试等待。"""
    def _run():
        db = SessionLocal()
        try:
            model = db.get(ModelConfig, model_id)
            conversation = db.get(Conversation, conversation_id)
            if model is None or conversation is None:
                return
            refresh_conversation_summary(db, model, build_llm(model), conversation)
        except Exception:
            logger.exception("后台刷新会话摘要失败 conversation_id=%s", conversation_id)
        finally:
            db.close()
    thread = threading.Thread(target=_run, name=f"summary-{conversation_id}", daemon=True)
    thread.start()
    return thread


def _rewrite_queries(model: ModelConfig, llm: Any, message_text: str) -> list[str]:
    """LLM 改写查询：生成多个利于检索的子查询（覆盖同义词/不同角度）。

    超时或失败时退回原查询，保证检索总能快速执行、不卡对话。
    熔断打开期间同样退回原查询不对外报错；本地超时也计入该模型的连续失败（上游异常由 guarded_invoke 记录）。
    """
    prompt = (
        "你是检索查询改写助手。把用户问题改写成 3 个更利于向量检索的查询短语，"
        "每个一行，尽量覆盖同义词和不同角度，只输出查询短语本身，不要编号、不要解释：\n\n"
        + message_text
    )

    def _invoke():
        return guarded_invoke(model, llm, prompt)

    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeoutError

    # 不能用 with：ThreadPoolExecutor 退出时会 shutdown(wait=True)，
    # 超时后仍要等那次慢调用返回，超时保护形同虚设（实测把对话首字节拖到 55 秒）。
    # 这里显式 shutdown(wait=False)，超时即放弃，慢调用在后台线程自行结束。
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        resp = executor.submit(_invoke).result(timeout=settings.RAG_QUERY_REWRITE_TIMEOUT_SECONDS)
        lines = [l.strip() for l in (resp.content or "").split("\n") if l.strip()]
        queries = [q.lstrip("1234567890.-)（） ").strip() for q in lines[:3]]
        queries = [q for q in queries if q]
    except Exception as e:
        # 超时或模型故障：退回原查询，检索仍可用但召回面变窄
        logger.warning("检索查询改写失败，使用原查询：%s: %s", type(e).__name__, e)
        if isinstance(e, FutureTimeoutError):
            # 本地超时时上游调用还在后台线程里跑，guarded_invoke 记不到这次"失败"，这里补记
            breaker.record_failure(model.id, model.name, e)
        queries = []
    finally:
        executor.shutdown(wait=False)
    return queries or [message_text]


def _queries_for(model: ModelConfig, llm: Any, message_text: str) -> list[str]:
    """检索用的查询集合：默认只用原问题；开启 RAG_QUERY_REWRITE_ENABLED 才让模型改写（多一次模型调用）。"""
    if not settings.RAG_QUERY_REWRITE_ENABLED:
        return [message_text]
    return _rewrite_queries(model, llm, message_text)


def _retrieve_all(kb_ids: list, queries: list, role: str | None) -> tuple[list, int, str | None]:
    """对每个 (知识库, 查询) 并行检索（各自开会话），按 (kb_id, chunk_id) 合并取最高分。返回 (引用列表, 鉴权剔除数, 重排模式)。"""
    pairs = [(kb_id, q) for kb_id in kb_ids for q in queries]
    top_k = settings_service.runtime_value("rag_top_k")  # 每库召回条数是运行时参数（页面可改），一次请求内取一次保持一致

    def _one(pair):
        return pair[0], retrieve_with_stats(pair[0], pair[1], top_k, role=role)

    if len(pairs) == 1:
        results = [_one(pairs[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(pairs))) as ex:
            results = list(ex.map(_one, pairs))
    merged: dict = {}
    acl_rejected = 0
    rerank_mode = None
    for kb_id, stats in results:
        acl_rejected += stats["stats"].get("acl_rejected", 0)
        rerank_mode = stats["stats"].get("rerank_mode") or rerank_mode
        for item in stats["items"]:
            key = (kb_id, item["chunk_id"])
            if key not in merged or item["score"] > merged[key]["score"]:
                merged[key] = {"kb_id": kb_id, "chunk_id": item["chunk_id"], "doc_name": item["doc_name"], "content": item["content"], "score": item["score"]}
    citations = sorted(merged.values(), key=lambda x: -x["score"])[: top_k * len(kb_ids)]
    return citations, acl_rejected, rerank_mode


def get_published_agent(db: Session, agent_id: int) -> Agent:
    """取已发布（published）的智能体；不存在抛 404，未发布抛 403。"""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise BizError(404, "智能体不存在")
    if agent.status != "published":
        raise BizError(403, "智能体未发布")
    return agent


def prepare_chat(db: Session, user_id: int, agent_id: int, message: str, conversation_id: int | None = None) -> tuple[int, int]:
    """校验智能体，获取/新建会话，落用户消息与运行记录。返回 (conversation_id, run_id)。"""
    agent = get_published_agent(db, agent_id)
    conversation = None
    if conversation_id:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise BizError(404, "会话不存在")
    if conversation is None:
        title = message.strip()[:settings.CHAT_TITLE_MAX_LEN] or "新对话"  # 先落瞬时标题，后台异步生成
        conversation = Conversation(agent_id=agent_id, user_id=user_id, title=title)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    db.add(Message(conversation_id=conversation.id, role="user", content=message))
    # model_id / conversation_id 是统计与追溯用的快照：智能体后来换模型不影响这条运行的归属
    run = run_service.create_run(
        db, "chat", user_id, agent_id=agent_id, model_id=agent.model_id, conversation_id=conversation.id,
        input_data={"message": message, "source": "chat"},
    )
    return conversation.id, run.id


def build_chat_context(db: Session, agent_id: int, message_text: str, conversation_id: int, role: str = None) -> ChatContext:
    """构建对话上下文：LLM、工具、系统提示（含 RAG 引用，带权限过滤 + 证据绑定）与多轮历史消息。"""
    agent = db.get(Agent, agent_id)
    model = db.get(ModelConfig, agent.model_id)
    if model is None or not model.is_enabled:
        raise BizError(400, "模型不可用")

    llm = build_llm(model)
    tool_dbs = db.query(Tool).filter(Tool.id.in_(agent.tool_ids)).all() if agent.tool_ids else []
    tools = build_tools(tool_dbs)

    kb_context = ""
    citations = []
    acl_rejected = 0
    rerank_mode = None
    started = time.perf_counter()
    if agent.kb_ids:
        queries = _queries_for(model, llm, message_text)
        citations, acl_rejected, rerank_mode = _retrieve_all(agent.kb_ids, queries, role)
        if citations:
            kb_context = (
                "【参考片段】只能依据下列片段作答，每条断言须标注片段编号 [n]，"
                "不得做超出材料的推测或跨片段拼接推导：\n"
                + "\n".join(f"[{i + 1}] {c['content']}" for i, c in enumerate(citations))
                + "\n\n约束：参考片段未覆盖的内容，如实回答『知识库中没有相关信息』，禁止编造。"
            )
    retrieval_ms = int((time.perf_counter() - started) * 1000)
    system_prompt = agent.system_prompt + (("\n\n" + kb_context) if kb_context else "")

    conversation = db.get(Conversation, conversation_id)
    history = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    # prepare_chat 已把本轮用户消息落库，历史里的最后一行就是它；不剔除会让模型收到两条相同的用户消息
    if history and history[-1].role == "user" and history[-1].content == message_text:
        history = history[:-1]
    lc_messages, summary_pending = _build_history_messages(conversation, history, settings.CHAT_HISTORY_MAX_MESSAGES)
    lc_messages.append(HumanMessage(content=message_text))
    logger.info("对话上下文就绪 agent_id=%s 检索 %dms 引用 %d 条 历史 %d 条", agent_id, retrieval_ms, len(citations), len(lc_messages) - 1)

    return ChatContext(model=model, llm=llm, tools=tools, system_prompt=system_prompt, citations=citations,
                       history_messages=lc_messages, acl_rejected=acl_rejected, rerank_mode=rerank_mode, summary_pending=summary_pending)


def save_assistant_message(db: Session, conversation_id: int, content: str, citations: list, usage: dict, tool_calls: list = None) -> Message:
    """落一条 assistant 消息（含引用、token 用量与工具调用记录）并返回。"""
    msg = Message(conversation_id=conversation_id, role="assistant", content=content, citations=citations, token_usage=usage, tool_calls=tool_calls or [])
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def finalize_run(db: Session, run_id: int, status: str, content: str = None, usage: dict = None, error: str = None) -> None:
    """对话结束收尾运行记录（委托 run_service.finalize_run，幂等：终态不会被二次覆盖）。"""
    run = db.get(Run, run_id)
    if run:
        output = {"content": content} if content is not None else None
        run_service.finalize_run(db, run, status, output=output, usage=usage, error=error)


def finalize_cancelled_chat(db: Session, run_id: int, conversation_id: int, partial_content: str,
                            citations: list, usage: dict, tool_calls: list) -> bool:
    """客户端中断（停止按钮/断网）时的收尾：已生成的部分回答落库，运行记录置为 cancelled。

    部分回答也要落库：界面上用户已经看到了这段内容，不存的话刷新后会只剩一条孤零零的用户消息。
    幂等：运行已是终态（正常 done 或 failed）则什么都不做，不会重复写消息。返回是否实际收尾。
    """
    run = db.get(Run, run_id)
    if run is None or run.status in run_service.FINAL_STATUSES:
        return False
    if partial_content:
        save_assistant_message(db, conversation_id, partial_content, citations, usage or {}, tool_calls)
    run_service.finalize_run(db, run, "cancelled", output={"content": partial_content}, usage=usage or None)
    return True
