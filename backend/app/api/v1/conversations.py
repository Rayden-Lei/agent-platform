"""会话（Conversation）路由：当前用户的会话列表、消息记录与删除。

本模块任意登录用户（JWT / API Key）可访问，数据归属校验在 service 层完成。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.services import conversation_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(
    params: PageParams = Depends(page_params),
    agent_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前用户的会话列表（分页），可按 agent_id 过滤。"""
    return conversation_service.list_conversations(db, user, params, agent_id)


@router.get("/{conversation_id}/messages")
def list_messages(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """指定会话下的消息列表。会话归属校验在 service 层完成。"""
    return conversation_service.list_messages(db, conversation_id, user)


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除指定会话（含其消息）。"""
    conversation_service.delete_conversation(db, conversation_id, user)
    return {"code": 0, "message": "ok"}
