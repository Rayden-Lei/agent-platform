"""用户管理路由。本模块所有接口仅限 admin 角色访问。"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import Page, UserCreate, UserOut, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


class ResetPasswordIn(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class UserBatchIn(BatchIn):
    action: Literal["enable", "disable", "delete"]


@router.get("", response_model=Page[UserOut])
def list_users(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="用户名模糊匹配"),
    role: Literal["admin", "developer", "caller"] | None = Query(None),
    is_active: bool | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    """用户列表（分页），支持用户名模糊、角色、启用状态过滤；sort 可选 id / username / created_at。"""
    return user_service.list_users(db, params, q, role, is_active, sort)


@router.post("", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """新建用户。"""
    return user_service.create_user(db, data)


# 固定路径必须声明在 /{user_id} 之前
@router.post("/batch")
def batch_users(data: UserBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """批量启用 / 停用 / 删除：逐条独立执行并返回成功与失败清单；对自己的停用 / 删除进失败清单。"""
    return run_batch(db, data.unique_ids(), lambda user_id: user_service.apply_batch_action(db, user_id, data.action, user))


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """按 ID 更新用户信息（角色 / 启用状态）；不能停用或降级自己。"""
    return user_service.update_user(db, user_id, data, user)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, data: ResetPasswordIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """管理员重置用户密码。"""
    user_service.reset_password(db, user_id, data.password, user)
    return {"code": 0, "message": "ok"}


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """按 ID 删除用户；不能删除自己；仍持有配置资源时 409。"""
    user_service.delete_user(db, user_id, user)
    return {"code": 0, "message": "ok"}
