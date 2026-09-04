"""用户管理路由。本模块所有接口仅限 admin 角色访问。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import Page, UserCreate, UserOut, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserOut])
def list_users(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=64, description="用户名模糊匹配"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    """用户列表（分页），支持用户名模糊匹配。"""
    return user_service.list_users(db, params, q)


@router.post("", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """新建用户。"""
    return user_service.create_user(db, data)


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """按 ID 更新用户信息。"""
    return user_service.update_user(db, user_id, data)


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """按 ID 删除用户。"""
    user_service.delete_user(db, user_id)
    return {"code": 0, "message": "ok"}
