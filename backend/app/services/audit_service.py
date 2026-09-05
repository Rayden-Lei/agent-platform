from datetime import datetime

from sqlalchemy.orm import Session

from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.models import AuditLog

SORTABLE = {"id": AuditLog.id, "created_at": AuditLog.created_at}


def list_audit_logs(db: Session, params: PageParams, action: str = None, resource: str = None, username: str = None,
                    resource_id: int = None, ip: str = None, created_from: datetime = None, created_to: datetime = None,
                    sort: SortParams = None) -> dict:
    """分页查询审计日志：action / resource / resource_id / ip 精确过滤，username 模糊匹配，时间左闭右开区间；默认按时间倒序。"""
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource:
        query = query.filter(AuditLog.resource == resource)
    if username:
        query = query.filter(AuditLog.username.ilike(f"%{username}%"))
    if resource_id is not None:
        query = query.filter(AuditLog.resource_id == resource_id)
    if ip:
        query = query.filter(AuditLog.ip == ip)
    if created_from is not None:
        query = query.filter(AuditLog.created_at >= created_from)
    if created_to is not None:
        query = query.filter(AuditLog.created_at < created_to)
    return paginate(apply_sort(query, sort, SORTABLE, [AuditLog.id.desc()]), params, lambda a: {
        "id": a.id, "user_id": a.user_id, "username": a.username, "action": a.action, "resource": a.resource,
        "resource_id": a.resource_id, "detail": a.detail, "ip": a.ip,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    })
