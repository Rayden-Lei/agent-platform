"""操作审计：把关键写操作记录到 AuditLog 表，供后台审计查询与合规追溯。只负责记录，不参与业务判定。"""
from app.core.request_context import get_client_ip
from app.db.models import AuditLog


def record_audit(db, user, action: str, resource: str, resource_id=None, detail=None, ip=None):
    """写入一条审计日志并提交。

    - user：操作者 User；为 None 时记为 anonymous（未登录的系统行为）
    - action / resource / resource_id：操作类型、目标资源与主键，如 ("create", "knowledge_base", 3)
    - detail：附加上下文（如变更前后值），需可 JSON 序列化
    - ip：来源 IP；不传时自动取请求上下文里的客户端 IP，无请求上下文（调度线程、脚本）时为空。
      调用点不必各自传 IP，中间件解析一次即可覆盖全部审计。
    注意：本函数内部自行 commit；若调用方在同一事务中还有未提交的修改，会一并提交，
    且此后无法再整体回滚。审计失败会随事务一起回滚。
    """
    log = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "anonymous",
        action=action,
        resource=resource,
        resource_id=resource_id,
        detail=detail or {},
        ip=ip or get_client_ip(),
    )
    db.add(log)
    db.commit()
