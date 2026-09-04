"""API Key 管理路由。

API Key 供外部系统调用执行类接口（如工作流运行）时使用，与 JWT 共用 Authorization: Bearer 头。
本模块仅允许 admin / developer 角色访问。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.services import api_key_service

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class ApiKeyIn(BaseModel):
    """创建 API Key 的请求体：名称必填，quota 为调用额度上限（默认 1000 次）。"""

    name: str
    quota: int = 1000


@router.get("")
def list_api_keys(params: PageParams = Depends(page_params), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """API Key 列表（分页）。"""
    return api_key_service.list_api_keys(db, params)


@router.post("")
def create_api_key(data: ApiKeyIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建 API Key。创建后返回密钥信息，供调用方保存。"""
    return api_key_service.create_api_key(db, data, user)


@router.post("/{key_id}/toggle")
def toggle_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """启用 / 停用指定 API Key（开关切换）。"""
    return api_key_service.toggle_api_key(db, key_id)


@router.delete("/{key_id}")
def delete_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除指定 API Key。"""
    api_key_service.delete_api_key(db, key_id)
    return {"code": 0, "message": "ok"}
