from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import settings
from app.core.exceptions import BizError
from app.db.models import Agent, Conversation, Message, ModelConfig, Run, Tool
from app.model_gateway.gateway import build_llm
from app.rag.retriever import retrieve, retrieve_with_stats
from app.tools.langchain_tools import build_tools


@dataclass
class ChatContext:
    llm: Any
    tools: list
    system_prompt: str
    citations: list
    history_messages: list
    acl_rejected: int = 0


def _history_to_messages(rows: list) -> list:
    """DB 历史行 → langchain 消息列表（仅取 user/assistant）。"""
    msgs = []
    for h in rows:
        if h.role == "user":
            msgs.append(HumanMessage(content=h.content))
        elif h.role == "assistant":
            msgs.append(AIMessage(content=h.content))
    return msgs


def _summarize_history(llm: Any, older: list) -> str:
    """用 LLM 把较早历史压缩为简短摘要；失败或为空时退回字符截断兜底。"""
    text = "\n".join(f"{m.type}: {m.content}" for m in older)
    prompt = (
        "你是对话摘要助手。请把下面的历史对话压缩成一段不超过 150 字的摘要，"
        "只保留用户目标、关键事实和已确认结论，不要编造信息：\n\n" + text
    )
    try:
        resp = llm.invoke(prompt)
        summary = (resp.content or "").strip() if resp else ""
    except Exception:
        summary = ""
    # 兜底：摘要不可用时按字符截断，保证 token 仍是有界的
    return summary or text[:2000]


def _build_history_messages(llm: Any, rows: list, max_messages: int) -> list:
    """有界历史：保留最近 max_messages 条，更早的压缩为摘要后以 SystemMessage 注入。"""
    if len(rows) <= max_messages:
        return _history_to_messages(rows)
    older = _history_to_messages(rows[:-max_messages])
    recent = _history_to_messages(rows[-max_messages:])
    summary = _summarize_history(llm, older)
    return [SystemMessage(content="以下是更早对话的摘要（非逐字历史）：\n" + summary)] + recent


def _rewrite_queries(llm: Any, message_text: str) -> list[str]:
    """LLM 改写查询：生成多个利于检索的子查询（覆盖同义词/不同角度）。

    带 10 秒超时，失败/超时/改写为空时退回原查询，保证检索总能快速执行、不卡对话。
    """
    prompt = (
        "你是检索查询改写助手。把用户问题改写成 3 个更利于向量检索的查询短语，"
        "每个一行，尽量覆盖同义词和不同角度，只输出查询短语本身，不要编号、不要解释：\n\n"
        + message_text
    )

    def _invoke():
        return llm.invoke(prompt)

    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            resp = ex.submit(_invoke).result(timeout=10)
        lines = [l.strip() for l in (resp.content or "").split("\n") if l.strip()]
        queries = [q.lstrip("1234567890.-)（） ").strip() for q in lines[:3]]
        queries = [q for q in queries if q]
    except Exception:
        queries = []
    return queries or [message_text]


def get_published_agent(db: Session, agent_id: int) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise BizError(404, "智能体不存在")
    if agent.status != "published":
        raise BizError(403, "智能体未发布")
    return agent


def prepare_chat(db: Session, user_id: int, agent_id: int, message: str, conversation_id: int | None = None) -> tuple[int, int]:
    """校验智能体，获取/新建会话，落用户消息与运行记录。返回 (conversation_id, run_id)。"""
    get_published_agent(db, agent_id)
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
    run = Run(run_type="chat", agent_id=agent_id, user_id=user_id, status="running", input={"message": message})
    db.add(run)
    db.commit()
    db.refresh(run)
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
    if agent.kb_ids:
        queries = _rewrite_queries(llm, message_text)
        merged: dict = {}
        for kb_id in agent.kb_ids:
            for q in queries:
                stats = retrieve_with_stats(kb_id, q, settings.RAG_TOP_K, role=role)
                acl_rejected += stats["stats"].get("acl_rejected", 0)
                for s in stats["items"]:
                    key = (kb_id, s["chunk_id"])
                    if key not in merged or s["score"] > merged[key]["score"]:
                        merged[key] = {"kb_id": kb_id, "chunk_id": s["chunk_id"], "doc_name": s["doc_name"], "content": s["content"], "score": s["score"]}
        citations = sorted(merged.values(), key=lambda x: -x["score"])[: settings.RAG_TOP_K * len(agent.kb_ids)]
        if citations:
            kb_context = (
                "【参考片段】只能依据下列片段作答，每条断言须标注片段编号 [n]，"
                "不得做超出材料的推测或跨片段拼接推导：\n"
                + "\n".join(f"[{i + 1}] {c['content']}" for i, c in enumerate(citations))
                + "\n\n约束：参考片段未覆盖的内容，如实回答『知识库中没有相关信息』，禁止编造。"
            )
    system_prompt = agent.system_prompt + (("\n\n" + kb_context) if kb_context else "")

    history = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    lc_messages = _build_history_messages(llm, history, settings.CHAT_HISTORY_MAX_MESSAGES)
    lc_messages.append(HumanMessage(content=message_text))

    return ChatContext(llm=llm, tools=tools, system_prompt=system_prompt, citations=citations, history_messages=lc_messages, acl_rejected=acl_rejected)


def save_assistant_message(db: Session, conversation_id: int, content: str, citations: list, usage: dict, tool_calls: list = None) -> Message:
    msg = Message(conversation_id=conversation_id, role="assistant", content=content, citations=citations, token_usage=usage, tool_calls=tool_calls or [])
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def finalize_run(db: Session, run_id: int, status: str, content: str = None, usage: dict = None, error: str = None) -> None:
    run = db.get(Run, run_id)
    if run:
        run.status = status
        if content is not None:
            run.output = {"content": content}
        if usage is not None:
            run.token_usage = usage
        if error:
            run.error = error
        db.commit()
