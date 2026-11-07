import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, NamedTuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import settings
from app.core.exceptions import BizError
from app.db.models import Agent, ApiKey, Conversation, KnowledgeBase, Message, ModelConfig, Run, Tool
from app.db.session import SessionLocal, rows_to_dict
from app.model_gateway import breaker
from app.model_gateway.gateway import build_llm, guarded_invoke
from app.rag.retriever import retrieve, retrieve_with_stats
from app.runtime.agent_config import AgentRunConfig, load_version_config, resolve_live_config, run_config_from_snapshot, snapshot_of, usable_model
from app.schemas import AgentIn
from app.services import agent_service, api_key_service, chat_trace, chat_turn, conversation_service, run_service, settings_service, skill_service
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
    trace: list = field(default_factory=list)  # 装配阶段的调用链步骤（改写、检索），只有调试才收集
    retrieval_ms: int = 0


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


def _split_history(conversation: Conversation, rows: list, max_messages: int) -> tuple[list, list, str]:
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


# 后台摘要刷新的并发闸门：每个会话结束后都会起一个线程调一次模型，
# 不设上限时高并发对话会把线程数、数据库连接数、上游并发三者一起拉爆
# （上游限流之后又反过来拖慢所有人的首字节）。
# 用信号量把"同时跑几个摘要"钉死在个位数：抢不到的直接跳过这一轮，
# 下一轮对话攒够批次还会再触发，摘要晚一轮不影响正确性。
_SUMMARY_SLOTS = threading.Semaphore(4)


def schedule_summary_refresh(model_id: int, conversation_id: int) -> threading.Thread | None:
    """响应结束后在后台线程刷新摘要：自己开会话，失败只记日志。返回线程对象便于测试等待。

    并发受 _SUMMARY_SLOTS 限制：抢不到槽位就跳过本轮（返回 None），
    下一条消息进来时还会再试 —— 摘要不是实时功能，晚一轮完全可接受。
    """
    if not _SUMMARY_SLOTS.acquire(blocking=False):
        logger.info("跳过本轮摘要刷新（后台并发已满）conversation_id=%s", conversation_id)
        return None

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
            _SUMMARY_SLOTS.release()

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


# 检索并发的进程级闸门（见 _retrieve_all）：同一时刻最多这么多 (库, 查询) 任务在跑。
# 取 8 = 单次请求的外层并发上限，保证单请求行为不变，只压住多请求叠加时的总量。
_RETRIEVAL_SLOTS = threading.BoundedSemaphore(8)


class Retrieval(NamedTuple):
    citations: list
    acl_rejected: int
    rerank_mode: str | None
    steps: list  # 每个 (知识库, 查询) 一条调用链步骤（chat_trace.retrieve_step），调试下发，线上暂不用


def _retrieve_all(kb_ids: list, queries: list, role: str | None, kb_names: dict | None = None, kb_scope: list | None = None) -> Retrieval:
    """对每个 (知识库, 查询) 并行检索（各自开会话），按 (kb_id, chunk_id) 合并取最高分。
    kb_scope 是 API Key 的 kb_ids（Key 发起的对话才传，检索按 Key 的范围放行，见 retriever.kb_allows）。"""
    pairs = [(kb_id, q) for kb_id in kb_ids for q in queries]
    top_k = settings_service.runtime_value("rag_top_k")  # 每库召回条数是运行时参数（页面可改），一次请求内取一次保持一致
    kb_names = kb_names or {}

    def _one(pair):
        # 每个 (库, 查询) 任务都要先抢进程级槽位：外层线程池最多 8 个并发，而每个任务内部
        # 还会按关键词数再开最多 8 个线程（retriever 的关键词召回），两者相乘是 64 路 DB 连接
        # + 64 路 embedding 请求 —— 20 个知识库 × 3 个改写查询就能打满，随后所有人的首字节一起变慢。
        # 闸门放在任务粒度上（而不是整个请求一次），这样单个请求仍能跑满，多请求叠加时被压住总数。
        with _RETRIEVAL_SLOTS:
            clock = chat_trace.Clock()
            result = retrieve_with_stats(pair[0], pair[1], top_k, role=role, kb_scope=kb_scope)
        return pair[0], result, chat_trace.retrieve_step(kb_names.get(pair[0], f"知识库 #{pair[0]}"), pair[1], result, clock)

    if len(pairs) == 1:
        results = [_one(pairs[0])]
    else:
        # 线程池只负责"别让单个请求串行"，真正的总闸门是 _RETRIEVAL_SLOTS
        with ThreadPoolExecutor(max_workers=min(8, len(pairs))) as ex:
            results = list(ex.map(_one, pairs))
    merged: dict = {}
    acl_rejected = 0
    rerank_mode = None
    for kb_id, stats, _ in results:
        acl_rejected += stats["stats"].get("acl_rejected", 0)
        rerank_mode = stats["stats"].get("rerank_mode") or rerank_mode
        for item in stats["items"]:
            key = (kb_id, item["chunk_id"])
            if key not in merged or item["score"] > merged[key]["score"]:
                merged[key] = {"kb_id": kb_id, "chunk_id": item["chunk_id"], "doc_name": item["doc_name"], "content": item["content"], "score": item["score"]}
    citations = sorted(merged.values(), key=lambda x: -x["score"])[: top_k * len(kb_ids)]
    return Retrieval(citations, acl_rejected, rerank_mode, [step for _, _, step in results])


# 幂等回放与会话/运行记录的开立已经下沉到 chat_turn（三种对话共用），这里转出旧名字，
# 调用方（路由、分享访客、测试）不需要改 import 路径
ReplayChat = chat_turn.ReplayChat
PreparedChat = chat_turn.PreparedTurn


def prepare_chat(db: Session, caller: conversation_service.Caller, agent_id: int, message: str, conversation_id: int | None = None,
                 client_message_id: str | None = None, api_key: ApiKey | None = None) -> PreparedChat | ReplayChat:
    """校验消息、智能体与会话，获取/新建会话，落用户消息与运行记录。

    所有拒绝都发生在写库之前：消息全是空白 400、API Key 的作用域里没有该智能体 403、
    智能体不存在 404 / 未发布或已下线 403、会话不属于该调用方或不属于该智能体 404。长度与字符集由路由的 ChatIn 管（422）；
    登录请求带 end_user 的 400 在构造 caller 时（conversation_service.caller_for）。
    caller 决定会话通道与归属（docs/15 3.7.1 / 3.6）：新会话按它的五项写入，续聊须五项一致；运行记录的来源按通道
    （ui → chat、api → api_key 并记 api_key_id、share → share 并记 share_id），user_id 同会话。
    api_key 只用于作用域判定（docs/15 3.7.1，2026-10-05 前 Key 能调归属人能调的任意已发布智能体）。
    幂等：续聊时带了会话里已出现过的 client_message_id，返回 ReplayChat（不落消息、不调模型）；
    首轮（不带 conversation_id）不在幂等范围内。并发的同一条撞上部分唯一索引时按"首次仍在生成"409。
    配置读线上版本（草稿与线上分离，FR-039）：运行记录的 model_id 与 agent_version 都取线上快照，不取草稿行。
    """
    chat_turn.validate_message(message)
    api_key_service.check_agent_scope(api_key, agent_id)
    live = resolve_live_config(db, agent_id)
    # 线上对话用的必定是某个发布版本（resolve_live_config 带版本号），为 None 只出现在装配页调试，那条路不走本函数
    agent_version = live.version
    assert agent_version is not None
    # 会话与运行记录的开立三种对话完全一样（归属五项、幂等回放、用户消息与运行记录同一次提交），
    # 已经下沉到 chat_turn.open_turn；这里只负责智能体特有的校验与"记哪个版本、哪个模型"
    prepared, replay = chat_turn.open_turn(
        db, caller, conversation_service.KIND_AGENT, agent_id, message, conversation_id, client_message_id,
        missing_detail="会话不存在或不属于该智能体", run_type="chat",
        input_data={"message": message}, model_id=live.model_id, agent_version=agent_version,
    )
    if replay is not None:
        return replay
    # open_turn 的返回是"二选一"：(PreparedTurn, None) 或 (None, ReplayChat)。回放已在上一条分支返回，
    # 走到这里 prepared 必定有值；检查器推不出这个关系，按路由里同一个口径断言一次。
    assert prepared is not None
    return prepared


def _skills_block(skills: list) -> str:
    """技能进系统提示的两段文本（docs/17 §4.2）：常驻正文在前、目录在后，都没有时返回空串。

    顺序有意为之：always_on 是"每轮都要遵守的规则"，模型对提示词开头更敏感；
    目录放后面，它是"还有哪些手册可查"的索引，属于按需参考。

    目录只列**非** always_on 的技能：常驻的正文已经在上面了，再列一次会让模型以为要去 load_skill，
    白白多一次工具调用与一轮 token。
    """
    if not skills:
        return ""
    on_demand = [s for s in skills if not s.always_on]
    parts = [skill_service.always_on_text(skills), skill_service.catalog_text(on_demand)]
    body = "\n\n".join(p for p in parts if p)
    return ("\n\n" + body) if body else ""


def _context_from_config(db: Session, cfg: AgentRunConfig, message_text: str, role: str | None, trace: bool = False,
                         kb_scope: list | None = None, allow_http_tools: bool = True,
                         run_id: int | None = None, source: str = "chat") -> ChatContext:
    """按一份智能体配置装配 LLM、工具与检索（含 RAG 引用，带权限过滤 + 证据绑定），历史消息由调用方补。
    线上对话与装配页调试共用；trace=True 时查知识库名称并记下改写步骤，给调用链用（线上省掉这次查询）。
    kb_scope：API Key 对话时传 Key 的 kb_ids，检索只放行公开库与范围内且归属人可见的库（docs/15 3.7.1）。
    allow_http_tools=False 时不装配绑定的外部工具（HTTP 与 MCP 都在其中；分享访客默认如此，
    docs/15 3.6 与 docs/17 §5.3 第 6 条），内置工具照常可用。
    run_id / source 传给工具的执行闸门（docs/16 P3a），决定被拒时能追到哪一轮、哪个来源。"""
    model = usable_model(db, cfg.model_id)
    llm = build_llm(model, cfg.params)  # 智能体参数覆盖模型默认（FR-042）
    tool_dbs = db.query(Tool).filter(Tool.id.in_(cfg.tool_ids)).all() if cfg.tool_ids and allow_http_tools else []
    # 技能（docs/17 §4）：按 skill_ids 现查 skills 表，正文不进快照，改技能立刻对线上生效
    skills = skill_service.enabled_skills(db, cfg.skill_ids)
    tools = build_tools(tool_dbs, source=source, agent_id=cfg.agent_id, run_id=run_id, skills=skills)

    kb_context = ""
    retrieval = Retrieval([], 0, None, [])
    steps: list = []
    started = time.perf_counter()
    if cfg.kb_ids:
        clock = chat_trace.Clock()
        queries = _queries_for(model, llm, message_text)
        if trace and settings.RAG_QUERY_REWRITE_ENABLED:
            steps.append(chat_trace.make_step("rewrite", "查询改写", clock, input={"message": message_text}, output=queries))
        kb_names = rows_to_dict(db.query(KnowledgeBase.id, KnowledgeBase.name).filter(KnowledgeBase.id.in_(cfg.kb_ids)).all()) if trace else None
        retrieval = _retrieve_all(cfg.kb_ids, queries, role, kb_names, kb_scope)
        steps.extend(retrieval.steps)
        if retrieval.citations:
            kb_context = (
                "【参考片段】只能依据下列片段作答，每条断言须标注片段编号 [n]，"
                "不得做超出材料的推测或跨片段拼接推导：\n"
                + "\n".join(f"[{i + 1}] {c['content']}" for i, c in enumerate(retrieval.citations))
                + "\n\n约束：参考片段未覆盖的内容，如实回答『知识库中没有相关信息』，禁止编造。"
            )
    retrieval_ms = int((time.perf_counter() - started) * 1000)
    # 技能分两段进系统提示：always_on 的正文常驻（每轮都要的规则），其余只进目录等模型按需加载
    system_prompt = cfg.system_prompt + _skills_block(skills) + (("\n\n" + kb_context) if kb_context else "")
    return ChatContext(model=model, llm=llm, tools=tools, system_prompt=system_prompt, citations=retrieval.citations, history_messages=[],
                       acl_rejected=retrieval.acl_rejected, rerank_mode=retrieval.rerank_mode, trace=steps if trace else [], retrieval_ms=retrieval_ms)


def build_chat_context(db: Session, agent_id: int, message_text: str, conversation_id: int, role: str | None = None,
                       agent_version: int | None = None, kb_scope: list | None = None, allow_http_tools: bool = True,
                       run_id: int | None = None, source: str = "chat") -> ChatContext:
    """构建线上对话的上下文：配置取 agent_version 指定的发布版本（对话执行器传 prepare_chat 定好的版本），
    不传时取当前线上版本；历史取会话里的消息（最近 N 条原文 + 更早的持久化摘要）。
    kb_scope、allow_http_tools、run_id、source 见 _context_from_config。"""
    cfg = load_version_config(db, agent_id, agent_version) if agent_version is not None else resolve_live_config(db, agent_id)
    ctx = _context_from_config(db, cfg, message_text, role, kb_scope=kb_scope, allow_http_tools=allow_http_tools,
                               run_id=run_id, source=source)

    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        # 会话必须存在（历史摘要挂在它上面）；不存在说明传入的 id 有问题，按 404 处理，
        # 与 prepare_chat 里"会话不存在或不属于该智能体"的口径一致。
        raise BizError(404, "会话不存在")
    history = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    # prepare_chat 已把本轮用户消息落库，历史里的最后一行就是它；不剔除会让模型收到两条相同的用户消息
    if history and history[-1].role == "user" and history[-1].content == message_text:
        history = history[:-1]
    lc_messages, summary_pending = _build_history_messages(conversation, history, settings.CHAT_HISTORY_MAX_MESSAGES)
    lc_messages.append(HumanMessage(content=message_text))
    ctx.history_messages, ctx.summary_pending = lc_messages, summary_pending
    logger.info("对话上下文就绪 agent_id=%s 检索 %dms 引用 %d 条 历史 %d 条", agent_id, ctx.retrieval_ms, len(ctx.citations), len(lc_messages) - 1)
    return ctx


@dataclass(frozen=True)
class DebugTurn:
    """装配页调试的一轮（docs/15 3.4）：调试对象的配置、前端带来的调试历史、source=debug 的运行记录。不建会话、不落消息。"""

    agent_id: int
    user_id: int
    role: str
    message: str
    history: tuple
    run_id: int
    config: AgentRunConfig
    config_source: str  # inline 编辑器当前内容 / draft 已保存的草稿 / live 线上版本


def prepare_debug(db: Session, user, agent_id: int, message: str, history: list[dict], config_source: str, config: AgentIn | None) -> DebugTurn:
    """解析调试对象的配置并建运行记录。所有拒绝都在写库之前：消息全空白 400、智能体不存在 404、
    inline / draft 的引用校验与保存同一口径（模型不存在 404、停用 400、工具或知识库缺失 400）、live 却从未发布 400。
    线上版本的模型后来被停用这类情况与线上对话一样，在流里以"模型不可用"结束。"""
    if not message.strip():
        raise BizError(400, "消息不能为空")
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise BizError(404, "智能体不存在")
    if config_source == "inline":
        if config is None:  # inline 就是"用请求里带的当前编辑器内容"，不带就没得调试
            raise BizError(400, "inline 调试必须带上当前配置")
        cfg = run_config_from_snapshot(agent_id, agent_service.inline_snapshot(db, config))
    elif config_source == "draft":
        draft = snapshot_of(agent)
        agent_service.validate_agent_config(db, draft["model_id"], draft["tool_ids"], draft["kb_ids"])
        cfg = run_config_from_snapshot(agent_id, draft)
    else:
        if agent.published_version is None:
            raise BizError(400, "智能体还没有发布过，没有线上版本可调试")
        cfg = load_version_config(db, agent_id, agent.published_version)
    # 调试运行照常记成本（模型消耗要能追溯），运营指标按 source=debug 排除（D-05）
    run = run_service.create_run(db, "chat", user.id, agent_id=agent_id, model_id=cfg.model_id,
                                 input_data={"message": message, "config_source": config_source}, source="debug", agent_version=cfg.version)
    return DebugTurn(agent_id, user.id, user.role, message, tuple(history), run.id, cfg, config_source)


def build_debug_context(db: Session, turn: DebugTurn) -> ChatContext:
    """调试上下文：配置取调试对象，历史用前端带来的调试历史，按与线上相同的记忆条数截断，不模拟会话摘要。
    工具闸门按 source=debug 判定（与线上对话分开留痕）。"""
    ctx = _context_from_config(db, turn.config, turn.message, turn.role, trace=True, run_id=turn.run_id, source="debug")
    recent = list(turn.history)[-settings.CHAT_HISTORY_MAX_MESSAGES:]
    ctx.history_messages = [HumanMessage(content=h["content"]) if h["role"] == "user" else AIMessage(content=h["content"]) for h in recent]
    ctx.history_messages.append(HumanMessage(content=turn.message))
    return ctx


def save_assistant_message(db: Session, conversation_id: int, content: str, citations: list, usage: dict, tool_calls: list | None = None,
                           run_id: int | None = None, reasoning: str | None = None) -> Message:
    """落一条 assistant 消息（含引用、token 用量、工具调用记录与思维链）并返回。run_id 是这一轮的运行记录，幂等回放据此找回首次的回答。"""
    msg = Message(conversation_id=conversation_id, role="assistant", content=content, citations=citations, token_usage=usage,
                  tool_calls=tool_calls or [], run_id=run_id, reasoning=(reasoning or None))
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def finalize_run(db: Session, run_id: int, status: str, content: str | None = None, usage: dict | None = None, error: str | None = None) -> None:
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
        save_assistant_message(db, conversation_id, partial_content, citations, usage or {}, tool_calls, run_id=run_id)
    run_service.finalize_run(db, run, "cancelled", output={"content": partial_content}, usage=usage or None)
    return True
