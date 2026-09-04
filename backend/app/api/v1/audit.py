"""审计日志查询路由。仅 admin 角色可访问，按操作 / 资源 / 用户名过滤。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.services import audit_service

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(
    params: PageParams = Depends(page_params),
    action: str | None = Query(None, max_length=64),
    resource: str | None = Query(None, max_length=64),
    username: str | None = Query(None, max_length=64, description="用户名模糊匹配"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    """审计日志列表（分页），支持按操作类型、资源、用户名过滤。"""
    return audit_service.list_audit_logs(db, params, action, resource, username)
