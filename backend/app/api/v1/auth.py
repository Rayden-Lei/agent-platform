"""认证路由：登录换取 Token、查询当前登录用户信息。"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import anonymous_rate_limit, get_current_user, is_api_key_request
from app.db.models import User
from app.db.session import get_db
from app.schemas import ChangePasswordIn, LoginIn, MeOut, TokenOut, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut, dependencies=[Depends(anonymous_rate_limit)])
def login(data: LoginIn, db: Session = Depends(get_db)):
    """登录接口（公开，无需鉴权）。按来源 IP 限流；用户名密码校验通过后返回 Token。"""
    return auth_service.login(db, data.username, data.password)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    """查询当前登录用户信息与对外地址 public_base_url（docs/15 PB-07）。需携带有效 Token（JWT 或 API Key）。必须改密的账号也能调（core/deps 放行）。"""
    return MeOut(**UserOut.model_validate(user).model_dump(), public_base_url=settings.PUBLIC_BASE_URL)


@router.put("/me/password", response_model=TokenOut)
def change_my_password(data: ChangePasswordIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """本人改密（docs/15 OP-04；1C 的个人中心复用）：只认登录令牌，API Key 403。
    成功后旧令牌与其他设备上的会话全部失效，返回新令牌；必须改密的账号也能调。"""
    if is_api_key_request(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API Key 不能修改密码")
    return auth_service.change_password(db, user, data.old_password, data.new_password)
