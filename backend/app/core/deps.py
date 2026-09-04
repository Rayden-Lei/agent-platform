from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_db
from app.services import api_key_service

bearer_scheme = HTTPBearer(auto_error=False)

# API Key 与 JWT 共用 Authorization: Bearer 头，按明文前缀分流；调用方不需要学第二种请求头
API_KEY_PREFIX = "ak_"


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """任何已登录身份：JWT 用户，或 API Key 的归属用户。鉴权来源记在 request.state.auth_via。"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未认证")
    token = credentials.credentials
    if token.startswith(API_KEY_PREFIX):
        user, api_key = api_key_service.authenticate(db, token)
        request.state.auth_via = "api_key"
        request.state.api_key_id = api_key.id
        return user
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效或已过期")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号不可用")
    request.state.auth_via = "jwt"
    return user


def is_api_key_request(request: Request) -> bool:
    return getattr(request.state, "auth_via", None) == "api_key"


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
