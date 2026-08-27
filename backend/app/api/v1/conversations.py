from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import Conversation, Message, User
from app.db.session import get_db

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [
        {"id": c.id, "agent_id": c.agent_id, "title": c.title, "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat()}
        for c in rows
    ]


@router.get("/{conversation_id}/messages")
def list_messages(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
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


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    db.delete(conv)
    db.commit()
    return {"code": 0, "message": "ok"}
