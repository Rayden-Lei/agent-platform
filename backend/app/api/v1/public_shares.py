"""分享访客路由（docs/15 3.6，PB-01）：不要平台 JWT，前缀 /public/shares/{code}。

资料与建会话之外的接口都带 Authorization: Bearer <访客令牌>，由 share_service.authenticate_guest 统一校验；
公开模式的令牌快到期时，响应头 X-Share-Token 带新令牌（SSE 响应同样在头里）。响应一律是访客口径，
不复用 conversation_service 的结构（会带出工具入参与结果、kb_id / chunk_id / score、用量）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.v1.chat import sse_stream
from app.config import settings
from app.core.deps import API_KEY_PREFIX, bearer_scheme, get_current_user
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import CALLER_ID_PATTERN
from app.services import chat_runner, chat_service, share_service

router = APIRouter(prefix="/public/shares/{code}", tags=["public-shares"])

RENEW_HEADER = "X-Share-Token"


class GuestSessionIn(BaseModel):
    password: str | None = Field(None, max_length=64)


class GuestChatIn(BaseModel):
    """访客对话请求体：同登录对话，但没有 end_user（访客身份来自令牌）。client_message_id 是幂等键（docs/15 3.7.1）。"""

    message: str = Field(min_length=1, max_length=settings.CHAT_MESSAGE_MAX_CHARS)
    conversation_id: int | None = None
    client_message_id: str | None = Field(None, pattern=CALLER_ID_PATTERN)


def _token(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    return credentials.credentials if credentials else None


def _renew(response: Response, guest: share_service.Guest) -> None:
    if guest.renewed_token:
        response.headers[RENEW_HEADER] = guest.renewed_token


def _platform_user(request: Request, credentials: HTTPAuthorizationCredentials | None, db: Session) -> User | None:
    """"仅登录"模式建会话时 Authorization 头里的平台 JWT（不接受 API Key）；没带为 None，由服务层按访问方式决定是否 401。"""
    if credentials is None:
        return None
    if credentials.credentials.startswith(API_KEY_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="分享访问不接受 API Key")
    return get_current_user(request, credentials, db)


@router.get("")
def share_info(code: str, db: Session = Depends(get_db)):
    """访客页资料：{agent_name, description, opening_statement, starter_questions, access_mode, password_required, show_citations}。
    不存在或已关闭 404；已过期、智能体已下线、创建者已停用 403。"""
    return share_service.public_info(db, code)


@router.post("/sessions")
def create_session(code: str, data: GuestSessionIn, request: Request, db: Session = Depends(get_db),
                   credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """领访客令牌：{guest_token, visitor_id, expires_at}。密码错 401；"仅登录"模式没带平台 JWT 401；每条分享 + 来源 IP 每分钟 ≤5 次。"""
    return share_service.create_session(db, code, data.password, _platform_user(request, credentials, db))


@router.post("/chat")
async def guest_chat(code: str, data: GuestChatIn, db: Session = Depends(get_db), credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """访客对话，SSE。事件按访客口径裁剪（share_service.guest_events）。令牌、限额、会话归属等拒绝都在建流之前以 HTTP 状态码返回，
    超限不建运行记录。"""
    guest = await run_in_threadpool(share_service.authenticate_guest, db, code, _token(credentials))
    await run_in_threadpool(share_service.check_chat_quota, db, guest)
    # 提交前取好：prepare_chat 提交后 ORM 对象过期，再读会多查一次
    allow_http_tools, show_citations, role = guest.share.allow_http_tools, guest.share.show_citations, guest.role
    caller = guest.caller()
    prepared = await run_in_threadpool(chat_service.prepare_chat, db, caller, guest.agent_id, data.message, data.conversation_id,
                                       data.client_message_id)
    headers = {RENEW_HEADER: guest.renewed_token} if guest.renewed_token else None
    if isinstance(prepared, chat_service.ReplayChat):
        events = chat_runner.replay_chat(prepared)
    else:
        turn = chat_runner.ChatTurn(agent_id=guest.agent_id, user_id=caller.user_id, role=role, message=data.message,
                                    conversation_id=prepared.conversation_id, run_id=prepared.run_id, agent_version=prepared.agent_version,
                                    allow_http_tools=allow_http_tools)
        events = chat_runner.stream_chat(turn)
    return StreamingResponse(sse_stream(share_service.guest_events(events, show_citations)), media_type="text/event-stream", headers=headers)


@router.get("/conversations")
def list_conversations(code: str, response: Response, params: PageParams = Depends(page_params),
                       q: str | None = Query(None, max_length=64, description="标题模糊匹配"), db: Session = Depends(get_db),
                       credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """本访客自己的会话（最近活跃在前），可按标题搜索；每项只有 {id, title, message_count, created_at, updated_at}。"""
    guest = share_service.authenticate_guest(db, code, _token(credentials))
    _renew(response, guest)
    return share_service.list_guest_conversations(db, guest, params, q)


@router.get("/conversations/{conversation_id}/messages")
def list_messages(code: str, conversation_id: int, response: Response, db: Session = Depends(get_db),
                  credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """本访客某个会话的消息（访客口径）；不是本访客的会话 404。"""
    guest = share_service.authenticate_guest(db, code, _token(credentials))
    _renew(response, guest)
    return share_service.list_guest_messages(db, guest, conversation_id)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(code: str, conversation_id: int, response: Response, db: Session = Depends(get_db),
                        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """删除本访客自己的会话；不是本访客的会话 404。"""
    guest = share_service.authenticate_guest(db, code, _token(credentials))
    _renew(response, guest)
    share_service.delete_guest_conversation(db, guest, conversation_id)
    return {"code": 0, "message": "ok"}
