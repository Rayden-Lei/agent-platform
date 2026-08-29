from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services import conversation_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return conversation_service.list_conversations(db, user)


@router.get("/{conversation_id}/messages")
def list_messages(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return conversation_service.list_messages(db, conversation_id, user)


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conversation_service.delete_conversation(db, conversation_id, user)
    return {"code": 0, "message": "ok"}
