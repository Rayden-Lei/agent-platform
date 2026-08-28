from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import AuditLog, User
from app.db.session import get_db

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(200).all()
    return [
        {"id": a.id, "username": a.username, "action": a.action, "resource": a.resource,
         "resource_id": a.resource_id, "detail": a.detail, "ip": a.ip,
         "created_at": a.created_at.isoformat() if a.created_at else None}
        for a in rows
    ]
