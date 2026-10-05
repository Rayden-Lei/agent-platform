import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.core import rate_limiter
from app.core.request_context import get_client_ip
from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_db
from app.services import api_key_service

logger = logging.getLogger(__name__)

# auto_error=False：凭据缺失/格式错误时不自动 401，统一由 get_current_user 给出中文错误信息
bearer_scheme = HTTPBearer(auto_error=False)

# API Key 与 JWT 共用 Authorization: Bearer 头，按明文前缀分流；调用方不需要学第二种请求头
API_KEY_PREFIX = "ak_"
# 必须改密的账号只能调这两个接口（docs/15 OP-04，服务端强制，不靠前端弹窗）；文案与前端 api/client.ts 一致
MUST_CHANGE_PASSWORD_DETAIL = "请先修改初始密码"
MUST_CHANGE_ALLOWED_PATHS = (f"{settings.API_V1_PREFIX}/auth/me", f"{settings.API_V1_PREFIX}/auth/me/password")


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """任何已登录身份：JWT 用户，或 API Key 的归属用户。鉴权来源记在 request.state.auth_via。

    同时把 API Key 的 id 记到 request.state.api_key_id（供审计/配额等场景使用），
    限流结果记到 request.state.rate_limit（中间件据此回写 X-RateLimit-* 响应头）；
    凭证缺失、JWT 无效/过期抛 401，用户不存在或停用抛 403。
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未认证")
    token = credentials.credentials
    if token.startswith(API_KEY_PREFIX):
        user, api_key, rate_limit = api_key_service.authenticate(db, token)
        request.state.auth_via = "api_key"
        request.state.api_key_id = api_key.id
        request.state.api_key = api_key  # 作用域判定要读 agent_ids / workflow_ids / kb_ids（docs/15 3.7.1），见 current_api_key
        request.state.rate_limit = rate_limit
        return user
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError) as e:
        # 只记异常类型与原因，绝不记 token 本身
        logger.info("JWT 校验失败：%s: %s", type(e).__name__, e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效或已过期")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号不可用")
    # 令牌版本对不上 = 签发之后重置过密码、停用过或改过密：旧会话作废。没有 ver 的令牌是 OP-04 之前签发的，
    # 那时所有人的版本都是 0，按 0 比对（之后任何一次吊销都会让它失效）
    if payload.get("ver", 0) != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")
    if user.must_change_password and request.url.path not in MUST_CHANGE_ALLOWED_PATHS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MUST_CHANGE_PASSWORD_DETAIL)
    # 登录用户维度限流：先鉴权再计数，无效 token 不占用户的额度
    rate_limit = rate_limiter.check("user", str(user.id), settings.RATE_LIMIT_USER_PER_MINUTE)
    if not rate_limit.allowed:
        raise rate_limiter.limit_exceeded(rate_limit)
    request.state.auth_via = "jwt"
    request.state.rate_limit = rate_limit
    return user


def anonymous_rate_limit(request: Request) -> None:
    """匿名接口（登录）按来源 IP 限流：暴力破解与撞库的第一道闸，在登录失败锁定之前生效。"""
    rate_limit = rate_limiter.check("ip", get_client_ip() or "unknown", settings.RATE_LIMIT_IP_PER_MINUTE)
    if not rate_limit.allowed:
        raise rate_limiter.limit_exceeded(rate_limit)
    request.state.rate_limit = rate_limit


def is_api_key_request(request: Request) -> bool:
    """本次请求是否通过 API Key 鉴权（由 get_current_user 写入 request.state.auth_via）。"""
    return getattr(request.state, "auth_via", None) == "api_key"


def current_api_key(request: Request):
    """本次请求所用的 API Key 行（JWT 请求为 None）。路由把它交给服务层做作用域与会话通道判定，服务层不读 HTTP 上下文。"""
    return getattr(request.state, "api_key", None) if is_api_key_request(request) else None


def require_roles(*roles: str, allow_api_key: bool = False):
    """角色校验。管理类接口默认只对 JWT 登录用户开放；
    需要让外部系统通过 API Key 调用的执行类接口（如工作流运行）显式传 allow_api_key=True。"""

    def checker(request: Request, user: User = Depends(get_current_user)) -> User:
        if not allow_api_key and is_api_key_request(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API Key 不能访问管理接口")
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限")
        return user

    return checker
