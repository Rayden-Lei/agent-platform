"""会话（Conversation）路由：当前调用方的会话列表、消息记录与删除。

本模块任意登录用户（JWT / API Key）可访问，数据归属校验在 service 层完成：登录只看本人在界面里的会话，
API Key 只看这个 Key 建的、且 end_user 一致的会话（docs/15 3.7.1）。end_user 只对 API Key 生效，登录请求带了 400。
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.deps import current_api_key, get_current_user
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import CALLER_ID_PATTERN
from app.services import conversation_service

router = APIRouter(prefix="/conversations", tags=["conversations"])

EndUser = Query(None, pattern=CALLER_ID_PATTERN, description="API Key 调用方的终端用户标识（与发起对话时一致）")


@router.get("")
def list_conversations(
    request: Request,
    params: PageParams = Depends(page_params),
    agent_id: int | None = Query(None),
    q: str | None = Query(None, max_length=64, description="标题模糊匹配"),
    end_user: str | None = EndUser,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前调用方的会话列表（分页），可按 agent_id 过滤、按标题搜索；附消息数与智能体名。"""
    return conversation_service.list_conversations(db, user, params, agent_id, q, api_key=current_api_key(request), end_user=end_user)


@router.get("/{conversation_id}")
def get_conversation(conversation_id: int, request: Request, end_user: str | None = EndUser, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """单个会话，结构同列表项；不属于当前调用方的 404（不暴露存在性）。"""
    return conversation_service.get_conversation(db, conversation_id, user, api_key=current_api_key(request), end_user=end_user)


@router.get("/{conversation_id}/messages")
def list_messages(conversation_id: int, request: Request, end_user: str | None = EndUser, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """指定会话下的消息列表。会话归属校验在 service 层完成。"""
    return conversation_service.list_messages(db, conversation_id, user, api_key=current_api_key(request), end_user=end_user)


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, request: Request, end_user: str | None = EndUser, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除指定会话（含其消息）。"""
    conversation_service.delete_conversation(db, conversation_id, user, api_key=current_api_key(request), end_user=end_user)
    return {"code": 0, "message": "ok"}
