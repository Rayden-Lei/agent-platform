from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate
from app.db.models import AuditLog


def list_audit_logs(db: Session, params: PageParams, action: str = None, resource: str = None, username: str = None) -> dict:
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource:
        query = query.filter(AuditLog.resource == resource)
    if username:
        query = query.filter(AuditLog.username.ilike(f"%{username}%"))
    return paginate(query.order_by(AuditLog.id.desc()), params, lambda a: {
        "id": a.id, "username": a.username, "action": a.action, "resource": a.resource,
        "resource_id": a.resource_id, "detail": a.detail, "ip": a.ip,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    })
