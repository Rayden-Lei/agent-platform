"""会话（Conversation）路由：当前调用方的会话列表、消息记录与删除。

本模块任意登录用户（JWT / API Key）可访问，数据归属校验在 service 层完成：登录只看本人在界面里的会话，
API Key 只看这个 Key 建的、且 end_user 一致的会话（docs/15 3.7.1）。end_user 只对 API Key 生效，登录请求带了 400。
分享访客的会话走 /public/shares/{code}/conversations（访客专用结构）。
"""

from typing import Literal

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


def _caller(request: Request, user: User, end_user: str | None) -> conversation_service.Caller:
    return conversation_service.caller_for(user, current_api_key(request), end_user)


@router.get("")
def list_conversations(
    request: Request,
    params: PageParams = Depends(page_params),
    kind: Literal["model", "agent", "workflow"] | None = Query(None, description="对话类型；不传则不限类型"),
    target_id: int | None = Query(None, description="按对话对象过滤（模型 / 智能体 / 工作流的 id），必须同时给 kind"),
    q: str | None = Query(None, max_length=64, description="标题模糊匹配"),
    end_user: str | None = EndUser,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前调用方的会话列表（分页），可按对话类型与对象过滤、按标题搜索；附消息数与对象名。

    三种对话共用一个列表接口（docs/17 §3.7）：kind 决定对话页的页签，target_id 决定"只看这个对象的会话"。
    原来的 agent_id 过滤已随对话分类型一次切换掉，不再兼容。
    """
    return conversation_service.list_conversations(db, _caller(request, user, end_user), params, kind, target_id, q)


@router.get("/{conversation_id}")
def get_conversation(conversation_id: int, request: Request, end_user: str | None = EndUser, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """单个会话，结构同列表项；不属于当前调用方的 404（不暴露存在性）。"""
    return conversation_service.get_conversation(db, conversation_id, _caller(request, user, end_user))


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: int,
    request: Request,
    end_user: str | None = EndUser,
    full_tool_results: bool = Query(False, description="返回落库的完整工具结果（≤ 8000 字），仅 admin / developer 的登录请求可用"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """指定会话下的消息列表。会话归属校验在 service 层完成。
    工具结果默认与实时事件同长（200 字）；排查时 admin / developer 带 full_tool_results=true 取库里那份（≤ 8000）。"""
    full_allowed = current_api_key(request) is None and user.role in ("admin", "developer")
    return conversation_service.list_messages(db, conversation_id, _caller(request, user, end_user), full_tool_results, full_allowed)


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, request: Request, end_user: str | None = EndUser, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除指定会话（含其消息）。"""
    conversation_service.delete_conversation(db, conversation_id, _caller(request, user, end_user))
    return {"code": 0, "message": "ok"}
