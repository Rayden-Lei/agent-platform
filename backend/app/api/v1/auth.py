"""认证路由：登录换取 Token、查询当前登录用户信息。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas import LoginIn, TokenOut, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    """登录接口（公开，无需鉴权）。用户名密码校验通过后返回 Token。"""
    return auth_service.login(db, data.username, data.password)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """查询当前登录用户信息。需携带有效 Token（JWT 或 API Key）。"""
    return UserOut.model_validate(user)
