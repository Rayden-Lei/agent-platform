from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.db.models import Conversation, Message, User


def _get_owned_conversation(db: Session, conversation_id: int, user: User) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise BizError(404, "会话不存在")
    return conv


def list_conversations(db: Session, user: User) -> list[dict]:
    rows = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [
        {"id": c.id, "agent_id": c.agent_id, "title": c.title,
         "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat()}
        for c in rows
    ]


def list_messages(db: Session, conversation_id: int, user: User) -> list[dict]:
    _get_owned_conversation(db, conversation_id, user)
    rows = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "citations": m.citations,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


def delete_conversation(db: Session, conversation_id: int, user: User) -> None:
    conv = _get_owned_conversation(db, conversation_id, user)
    db.delete(conv)
    db.commit()
