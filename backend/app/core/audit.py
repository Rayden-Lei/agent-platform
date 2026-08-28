from app.db.models import AuditLog


def record_audit(db, user, action: str, resource: str, resource_id=None, detail=None, ip=None):
    log = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "anonymous",
        action=action,
        resource=resource,
        resource_id=resource_id,
        detail=detail or {},
        ip=ip,
    )
    db.add(log)
    db.commit()
