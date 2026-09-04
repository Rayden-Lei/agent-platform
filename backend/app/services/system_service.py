"""系统运行状态：把各处的降级与故障汇总到一个接口。

存在的理由：平台有多处"失败了也能继续跑"的降级路径（向量模型退 hash、Redis 挂了限流失效），
它们不报错、不影响接口返回，只会让效果变差。没有这个接口就只能等人肉发现。
"""
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ScheduledJob
from app.rag.embeddings import MODE_MODEL, embedding_status
from app.services import auth_service

logger = logging.getLogger(__name__)


def _database_status(db: Session) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "reason": None}
    except SQLAlchemyError as e:
        logger.warning("数据库探测失败：%s", e)
        return {"ok": False, "reason": str(e)[:200]}


def _scheduler_status(db: Session) -> dict:
    """已注册任务数与库中启用任务数不一致，通常意味着有任务的 cron 非法而被跳过。"""
    enabled = db.query(ScheduledJob).filter(ScheduledJob.is_enabled == True).count()  # noqa: E712
    try:
        from app.core.scheduler import get_scheduler

        sched = get_scheduler()
        registered = len(sched.get_jobs())
        return {"running": bool(sched.running), "registered_jobs": registered, "enabled_jobs": enabled}
    except Exception as e:
        logger.exception("读取调度器状态失败")
        return {"running": False, "registered_jobs": 0, "enabled_jobs": enabled, "reason": str(e)[:200]}


def get_system_status(db: Session) -> dict:
    """汇总运行状态。degraded 非空即代表当前有能力在降级运行，前端据此提示。"""
    database = _database_status(db)
    embedding = embedding_status()
    login_guard = auth_service.login_guard_status()
    scheduler = _scheduler_status(db)

    degraded = []
    if embedding["mode"] != MODE_MODEL:
        degraded.append({"item": "embedding", "message": embedding["reason"]})
    if not login_guard["enabled"]:
        degraded.append({"item": "login_guard", "message": f"登录限流未生效：{login_guard['reason']}"})
    if not database["ok"]:
        degraded.append({"item": "database", "message": f"数据库不可用：{database['reason']}"})
    if not scheduler["running"]:
        degraded.append({"item": "scheduler", "message": "调度器未运行，定时任务不会触发"})
    elif scheduler["registered_jobs"] < scheduler["enabled_jobs"]:
        missing = scheduler["enabled_jobs"] - scheduler["registered_jobs"]
        degraded.append({"item": "scheduler", "message": f"{missing} 个启用的定时任务未注册，通常是 cron 表达式非法"})

    return {
        "app": settings.APP_NAME,
        "database": database,
        "embedding": embedding,
        "login_guard": login_guard,
        "scheduler": scheduler,
        "degraded": degraded,
    }
