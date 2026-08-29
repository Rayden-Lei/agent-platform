from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from langchain_core.messages import AIMessage, HumanMessage

from app.config import settings
from app.core.exceptions import BizError
from app.db.models import Agent, Conversation, Message, ModelConfig, Run, Tool
from app.model_gateway.gateway import build_llm
from app.rag.retriever import retrieve
from app.tools.langchain_tools import build_tools


@dataclass
class ChatContext:
    llm: Any
    tools: list
    system_prompt: str
    citations: list
    history_messages: list


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
        conversation = Conversation(agent_id=agent_id, user_id=user_id, title=message[:30])
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    db.add(Message(conversation_id=conversation.id, role="user", content=message))
    run = Run(run_type="chat", agent_id=agent_id, user_id=user_id, status="running", input={"message": message})
    db.add(run)
    db.commit()
    db.refresh(run)
    return conversation.id, run.id


def build_chat_context(db: Session, agent_id: int, message_text: str, conversation_id: int) -> ChatContext:
    """构建对话上下文：LLM、工具、系统提示（含 RAG 引用）与多轮历史消息。"""
    agent = db.get(Agent, agent_id)
    model = db.get(ModelConfig, agent.model_id)
    if model is None or not model.is_enabled:
        raise BizError(400, "模型不可用")

    llm = build_llm(model)
    tool_dbs = db.query(Tool).filter(Tool.id.in_(agent.tool_ids)).all() if agent.tool_ids else []
    tools = build_tools(tool_dbs)

    kb_context = ""
    citations = []
    if agent.kb_ids:
        for kb_id in agent.kb_ids:
            for s in retrieve(kb_id, message_text, settings.RAG_TOP_K):
                citations.append({"kb_id": kb_id, "doc_name": s["doc_name"], "content": s["content"], "score": s["score"]})
        if citations:
            kb_context = "以下是与问题相关的知识，请优先参考：\n" + "\n".join(
                f"[{i + 1}] {c['content']}" for i, c in enumerate(citations)
            )
    system_prompt = agent.system_prompt + (("\n\n" + kb_context) if kb_context else "")

    history = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    lc_messages = []
    for h in history:
        if h.role == "user":
            lc_messages.append(HumanMessage(content=h.content))
        elif h.role == "assistant":
            lc_messages.append(AIMessage(content=h.content))
    lc_messages.append(HumanMessage(content=message_text))

    return ChatContext(llm=llm, tools=tools, system_prompt=system_prompt, citations=citations, history_messages=lc_messages)


def save_assistant_message(db: Session, conversation_id: int, content: str, citations: list, usage: dict) -> Message:
    msg = Message(conversation_id=conversation_id, role="assistant", content=content, citations=citations, token_usage=usage)
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
