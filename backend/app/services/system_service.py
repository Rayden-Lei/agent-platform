"""系统运行状态：把各处的降级与故障汇总到一个接口。

存在的理由：平台有多处"失败了也能继续跑"的降级路径（向量模型退 hash、Redis 挂了限流失效），
它们不报错、不影响接口返回，只会让效果变差。没有这个接口就只能等人肉发现。
"""
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.core import rate_limiter
from app.core.request_context import get_client_ip
from app.db.models import ScheduledJob
from app.model_gateway import breaker
from app.rag.embeddings import MODE_MODEL, embedding_status
from app.rag.rerank import rerank_status
from app.services import auth_service

logger = logging.getLogger(__name__)


def _database_status(db: Session) -> dict:
    """探测数据库连通性；失败只记日志并返回降级状态，不让健康检查本身抛错。"""
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


def _client_ip_status(real_ip_header: bool) -> dict:
    """来源 IP 是否可信（docs/15 PB-07）：开了 TRUSTED_PROXY_ENABLED 却没收到合法的 X-Real-IP，说明代理没有覆写来源，
    后端会退到 X-Forwarded-For 首项（客户端能伪造），按 IP 的限流、登录尝试次数与 Key 来源白名单都可能被绕过。
    开关没开时不判定：本机开发经代理访问时来源恒为回环地址，属预期；开关是否该开由上线步骤把关（分享开放前提）。"""
    return {"trusted_proxy": settings.TRUSTED_PROXY_ENABLED, "real_ip_header": real_ip_header, "resolved": get_client_ip(),
            "ok": not settings.TRUSTED_PROXY_ENABLED or real_ip_header}


def get_system_status(db: Session, real_ip_header: bool = False) -> dict:
    """汇总运行状态。degraded 非空即代表当前有能力在降级运行，前端据此提示。
    real_ip_header：本次请求是否带了合法的 X-Real-IP（路由层判定），用于来源 IP 自检。"""
    database = _database_status(db)
    embedding = embedding_status()
    login_guard = auth_service.login_guard_status()
    rate_limit = rate_limiter.status()
    model_breakers = breaker.status()
    scheduler = _scheduler_status(db)
    client_ip = _client_ip_status(real_ip_header)

    degraded = []
    if not client_ip["ok"]:
        degraded.append({"item": "client_ip", "message": "代理没有覆写 X-Real-IP，来源 IP 不可信：按 IP 的限流与 API Key 来源白名单可能被伪造绕过"})
    if embedding["mode"] != MODE_MODEL:
        degraded.append({"item": "embedding", "message": embedding["reason"]})
    rerank = rerank_status()
    # 未配置重排模型属配置性降级不进 degraded；配置了但调用失败才是故障
    if rerank["configured"] and rerank["last_error"] is not None:
        degraded.append({"item": "rerank", "message": rerank["reason"]})
    if not login_guard["enabled"]:
        degraded.append({"item": "login_guard", "message": f"登录限流未生效：{login_guard['reason']}"})
    # 配置关闭（configured=False）是有意为之，不算降级；配置打开但 Redis 故障才是
    if rate_limit["configured"] and not rate_limit["enabled"]:
        degraded.append({"item": "rate_limit", "message": f"入口限流未生效：{rate_limit['reason']}"})
    for b in model_breakers:
        if b["state"] == breaker.STATE_OPEN:
            degraded.append({"item": "model_breaker", "message": f"模型「{b['name']}」熔断中，{b['retry_after_seconds']} 秒后自动重试"})
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
        "rerank": rerank,
        "login_guard": login_guard,
        "rate_limit": rate_limit,
        "model_breakers": model_breakers,
        "scheduler": scheduler,
        "client_ip": client_ip,
        "degraded": degraded,
    }
