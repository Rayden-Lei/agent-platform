"""系统运行状态：把各处的降级与故障汇总到一个接口。

存在的理由：平台有多处"失败了也能继续跑"的降级路径（向量模型退 hash、Redis 挂了限流失效），
它们不报错、不影响接口返回，只会让效果变差。没有这个接口就只能等人肉发现。
"""
import logging
import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.core import rate_limiter
from app.core.request_context import get_client_ip
from app.db.models import EmbeddingModel, KnowledgeBase, ScheduledJob
from app.model_gateway import breaker
from app.rag.embeddings import MODE_MODEL, embedding_status
from app.rag.rerank import rerank_status
from app.rag.retriever import unsearchable_reason
from app.runtime import sandbox
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
    """已注册任务数与库中启用任务数不一致，通常意味着有任务的 cron 非法而被跳过。

    **用 peek_scheduler 而不是 get_scheduler**：这是只读状态接口，
    不能因为有人探活就把后台调度线程拉起来（见 scheduler.peek_scheduler 的说明）。
    调度器没启动时运行状态如实报 False，注册数记 0。

    多实例选主（2026-11-18）：is_leader 表示本实例是否持有调度锁。
    False 时 registered_jobs 为 0 是**正常**的（定时任务由持锁实例执行），不能报成降级，
    否则每个从实例都会让全局横幅一直挂着"N 个任务未注册"。
    """
    enabled = db.query(ScheduledJob).filter(ScheduledJob.is_enabled == True).count()  # noqa: E712
    try:
        from app.core.scheduler import is_leader, peek_scheduler

        sched = peek_scheduler()
        if sched is None:
            # 未启动 = 没尝试过选主，is_leader 如实报 None（前端据此区分"未启动"与"从实例"）
            return {"running": False, "registered_jobs": 0, "enabled_jobs": enabled, "is_leader": None}
        registered = len(sched.get_jobs())
        return {"running": bool(sched.running), "registered_jobs": registered, "enabled_jobs": enabled,
                "is_leader": is_leader()}
    except Exception as e:
        logger.exception("读取调度器状态失败")
        return {"running": False, "registered_jobs": 0, "enabled_jobs": enabled, "is_leader": None, "reason": str(e)[:200]}


# 状态接口里最多列出多少个不可检索的库：库可能很多（一次事故里所有绑同一个模型的库全不可用），
# 状态接口不该变成"全表返回"。超过上限时如实说"还有 N 个"，不假装只有这些。
UNSEARCHABLE_KB_LIMIT = 20


def _unsearchable_kbs(db: Session) -> list[dict]:
    """当前检索不了的知识库：[{id, name, embedding_model_id, reason}]。

    为什么要有：库绑定的向量模型被停用或删除后，retriever 只会让该库"不出结果"并记一条 warning ——
    对话里看着就是"知识库没有相关内容"，没人能发现是配置坏了（docs/09 已登记）。
    判断规则与检索路径共用 retriever.unsearchable_reason，状态页与检索不会各说一套。

    两次查询：一次取全部库的 (id, name, embedding_model_id)，一次按这批 id 取模型行；
    不在循环里 db.get（06 第 1 节：循环内不发 IO）。
    """
    rows = db.query(KnowledgeBase.id, KnowledgeBase.name, KnowledgeBase.embedding_model_id).order_by(KnowledgeBase.id).all()
    if not rows:
        return []
    model_ids = {r[2] for r in rows if r[2]}
    models = {m.id: m for m in db.query(EmbeddingModel).filter(EmbeddingModel.id.in_(model_ids)).all()} if model_ids else {}
    broken = []
    for kb_id, name, model_id in rows:
        reason = unsearchable_reason(name, model_id, models.get(model_id))
        if reason:
            broken.append({"id": kb_id, "name": name, "embedding_model_id": model_id, "reason": reason})
    return broken


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
    unsearchable = _unsearchable_kbs(db)
    # 沙箱降级意味着代码节点与技能脚本能读到宿主文件（挡不住越权读），必须让人看得见
    sandbox_status = sandbox.status()

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
    # 配置关闭（configured=False）是有意为之，不算降级；配置打开但 Redis 故障才是。
    # 文案要说清降级方向（2026-11-18）：公开入口 fail-closed 时是"被拒绝"而非"没保护"，
    # 两者的处置完全不同 —— 前者要尽快修 Redis 恢复可用性，后者是成本敞口。
    if rate_limit["configured"] and not rate_limit["enabled"]:
        if rate_limit.get("public_fail_closed"):
            message = f"入口限流降级：公开入口（分享/访客/来源 IP）已改为拒绝访问，内部接口放行：{rate_limit['reason']}"
        else:
            message = f"入口限流降级：所有入口均放行，无速率保护：{rate_limit['reason']}"
        degraded.append({"item": "rate_limit", "message": message})
    for b in model_breakers:
        if b["state"] == breaker.STATE_OPEN:
            degraded.append({"item": "model_breaker", "message": f"模型「{b['name']}」熔断中，{b['retry_after_seconds']} 秒后自动重试"})
    if not database["ok"]:
        degraded.append({"item": "database", "message": f"数据库不可用：{database['reason']}"})
    if not scheduler["running"]:
        degraded.append({"item": "scheduler", "message": "调度器未运行，定时任务不会触发"})
    elif scheduler["is_leader"] is False:
        # 从实例不注册任务属预期（定时任务由持锁实例执行），不能报成"任务未注册"的故障。
        # 但要让人知道"这台不干活"：多实例部署时据此确认选主确实生效了。
        pass
    elif scheduler["registered_jobs"] < scheduler["enabled_jobs"]:
        missing = scheduler["enabled_jobs"] - scheduler["registered_jobs"]
        degraded.append({"item": "scheduler", "message": f"{missing} 个启用的定时任务未注册，通常是 cron 表达式非法"})
    # 库绑定的向量模型被停用/删除后检索只会安静地返回空，用户分不清"库里没内容"和"库坏了"，
    # 所以每有一个这样的库就进一条 degraded（带库名，前端降级面板直接可读）
    for kb in unsearchable:
        degraded.append({"item": "kb_unsearchable", "message": f"知识库「{kb['name']}」当前无法检索：{kb['reason']}"})
    # 只在 Linux 上进 degraded 列表：macOS 本机开发永远降级（bwrap 只有 Linux 版），
    # 每次都弹全局横幅只是噪音。但降级原因仍然原样放在 sandbox 字段里，系统参数页能看到。
    if sandbox_status["degraded"] and sys.platform.startswith("linux"):
        degraded.append({"item": "sandbox", "message": f"代码执行沙箱降级：{sandbox_status['reason']}"})

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
        "sandbox": sandbox_status,
        # 检索不了的知识库清单（有界：最多 UNSEARCHABLE_KB_LIMIT 条，另给总数与截断数）。
        # 前端不必解析 degraded 的文案就能拿到结构化数据（库 id / 名称 / 原因）。
        "unsearchable_kbs": {
            "items": unsearchable[:UNSEARCHABLE_KB_LIMIT],
            "total": len(unsearchable),
            "truncated": max(0, len(unsearchable) - UNSEARCHABLE_KB_LIMIT),
        },
        "degraded": degraded,
    }
