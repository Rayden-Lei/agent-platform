"""认证路由：登录换取 Token、当前用户信息，以及个人中心（docs/15 OP-03）：改资料、改密码、退出其他设备、登录记录、我的 API 密钥。

个人中心的写操作与"我的 API 密钥"只认登录令牌（JWT），API Key 一律 403——拿着 Key 的外部系统不该能改归属人的资料、
踢掉归属人的登录，也不该能列出同一个人的其他 Key。
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.deps import anonymous_rate_limit, get_current_user, is_api_key_request
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import ChangePasswordIn, LoginIn, MeOut, ProfileUpdateIn, TokenOut
from app.services import api_key_service, auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _jwt_only(request: Request, action: str) -> None:
    if is_api_key_request(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"API Key 不能{action}")


@router.post("/login", response_model=TokenOut, dependencies=[Depends(anonymous_rate_limit)])
def login(data: LoginIn, db: Session = Depends(get_db)):
    """登录接口（公开，无需鉴权）。按来源 IP 限流；用户名密码校验通过后返回 Token。"""
    return auth_service.login(db, data.username, data.password)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    """当前登录用户、对外地址 public_base_url（docs/15 PB-07）与个人资料（手机号脱敏，OP-03）。JWT 或 API Key 都能调；
    必须改密的账号也能调（core/deps 放行）。"""
    return auth_service.profile_of(user)


@router.put("/me", response_model=MeOut)
def update_me(data: ProfileUpdateIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """改本人资料：显示名、邮箱、手机号（不带的不改，null 清除）。只认 JWT。"""
    _jwt_only(request, "修改资料")
    return auth_service.update_profile(db, user, data)


@router.put("/me/password", response_model=TokenOut)
def change_my_password(data: ChangePasswordIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """本人改密（docs/15 OP-04；个人中心复用）：只认登录令牌，API Key 403。
    成功后旧令牌与其他设备上的会话全部失效，返回新令牌；必须改密的账号也能调。"""
    _jwt_only(request, "修改密码")
    return auth_service.change_password(db, user, data.old_password, data.new_password)


@router.post("/me/logout-others", response_model=TokenOut)
def logout_others(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """退出其他设备：本人此前的令牌全部失效，返回新令牌供当前页面继续用。只认 JWT。"""
    _jwt_only(request, "退出其他设备")
    return auth_service.logout_others(db, user)


@router.get("/me/logins")
def my_logins(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """本人近 90 天最近 20 次登录（含用本人用户名的失败尝试）：[{created_at, ip, success}]，新的在前。只认 JWT。"""
    _jwt_only(request, "查看登录记录")
    return auth_service.login_history(db, user)


@router.get("/me/api-keys")
def my_api_keys(request: Request, params: PageParams = Depends(page_params), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """归属本人的 API Key（只读，任何角色都能看——调用者看的是管理员代发给自己的，docs/15 D-15）。
    结构同 GET /api-keys 的列表项，永不含明文。只认 JWT。"""
    _jwt_only(request, "查看 API Key 列表")
    return api_key_service.list_my_api_keys(db, user, params)
