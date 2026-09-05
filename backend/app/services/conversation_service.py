from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import Agent, Conversation, Message, User


def _get_owned_conversation(db: Session, conversation_id: int, user: User) -> Conversation:
    """取当前用户拥有的会话；非本人会话统一按 404 处理，避免泄露会话存在性。"""
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise BizError(404, "会话不存在")
    return conv


def list_conversations(db: Session, user: User, params: PageParams, agent_id: int = None, q: str = None) -> dict:
    """分页列出当前用户的会话，可按智能体过滤、按标题模糊搜索，按更新时间倒序（最近活跃在前）。
    附带消息数与智能体名：消息数用一次分组查询，智能体名用一次 IN 查询，不逐行查库。"""
    query = db.query(Conversation).filter(Conversation.user_id == user.id)
    if agent_id:
        query = query.filter(Conversation.agent_id == agent_id)
    if q:
        query = query.filter(Conversation.title.ilike(f"%{q}%"))
    query = query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    page = paginate(query, params)
    rows = page["items"]
    ids = [c.id for c in rows]
    counts = dict(db.query(Message.conversation_id, func.count(Message.id)).filter(Message.conversation_id.in_(ids)).group_by(Message.conversation_id).all()) if ids else {}
    agent_ids = {c.agent_id for c in rows if c.agent_id}
    agent_names = dict(db.query(Agent.id, Agent.name).filter(Agent.id.in_(agent_ids)).all()) if agent_ids else {}
    page["items"] = [{
        "id": c.id, "agent_id": c.agent_id, "agent_name": agent_names.get(c.agent_id), "title": c.title, "summary": c.summary,
        "message_count": int(counts.get(c.id, 0)),
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    } for c in rows]
    return page


def list_messages(db: Session, conversation_id: int, user: User) -> list[dict]:
    """取会话内全部消息（按 ID 升序，即对话顺序），先校验会话归属。token_usage 随消息返回，刷新后历史消息仍能显示用量。"""
    _get_owned_conversation(db, conversation_id, user)
    rows = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "citations": m.citations,
            "token_usage": m.token_usage or None,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


def delete_conversation(db: Session, conversation_id: int, user: User) -> None:
    """删除会话（消息随外键 CASCADE 级联删除），先校验会话归属。"""
    conv = _get_owned_conversation(db, conversation_id, user)
    db.delete(conv)
    db.commit()
