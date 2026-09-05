"""审计日志查询路由。仅 admin 角色可访问，按操作 / 资源 / 用户名 / 资源 ID / IP / 时间区间过滤。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params, time_range
from app.db.models import User
from app.db.session import get_db
from app.services import audit_service

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    action: str | None = Query(None, max_length=64),
    resource: str | None = Query(None, max_length=64),
    username: str | None = Query(None, max_length=64, description="用户名模糊匹配"),
    resource_id: int | None = Query(None),
    ip: str | None = Query(None, max_length=64),
    created_from: datetime | None = Query(None, description="时间下界（含），ISO 8601 带时区"),
    created_to: datetime | None = Query(None, description="时间上界（不含），ISO 8601 带时区"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    """审计日志列表（分页），支持按操作类型、资源、用户名、资源 ID、IP、时间区间过滤；sort 可选 id / created_at。"""
    created_from, created_to = time_range(created_from, created_to)
    return audit_service.list_audit_logs(db, params, action, resource, username, resource_id, ip, created_from, created_to, sort)
