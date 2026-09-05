"""运营统计（页面深度优化）：按天趋势、按模型 / 智能体 / 工作流聚合、工作台概览。

全部在数据库侧聚合，不拉明细行；时间窗按 REPORT_TIMEZONE 切天（库里存 UTC）。
成本口径与 run_service 一致：读运行记录收尾时落库的 cost 快照（改单价不追溯）；workflow 运行没有模型，成本为 0 但计入运行数与 token。
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, and_, case, cast, func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Agent, ApiKey, Conversation, Document, KnowledgeBase, Message, ModelConfig, PromptTemplate, Run, ScheduledJob,
    Tool, User, Workflow,
)
from app.model_gateway import breaker
from app.services import run_service, system_service


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.REPORT_TIMEZONE)


def _window(days: int) -> tuple[datetime, list[str]]:
    """最近 days 天（含今天）的起点（UTC）与逐日标签（YYYY-MM-DD，业务时区）。"""
    today = datetime.now(_tz()).date()
    start_local = datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=_tz())
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    return start_local.astimezone(timezone.utc), labels


def _tokens(key: str):
    return func.coalesce(cast(Run.token_usage[key].astext, BigInteger), 0)


def _status_count(status: str):
    return func.coalesce(func.sum(case((Run.status == status, 1), else_=0)), 0)


def _avg_latency():
    """只对已结束的运行算平均耗时；running / awaiting_review 的 latency_ms 是 0，混进去会把均值拉低。"""
    return func.avg(case((Run.finished_at.isnot(None), Run.latency_ms), else_=None))


_METRICS = [
    ("total", func.count(Run.id)),
    ("success", _status_count("success")),
    ("failed", _status_count("failed")),
    ("cancelled", _status_count("cancelled")),
    ("awaiting_review", _status_count("awaiting_review")),
    ("running", _status_count("running")),
    ("prompt_tokens", func.coalesce(func.sum(_tokens("prompt_tokens")), 0)),
    ("completion_tokens", func.coalesce(func.sum(_tokens("completion_tokens")), 0)),
    ("total_tokens", func.coalesce(func.sum(_tokens("total_tokens")), 0)),
]


def _metric_columns():
    return [expr.label(name) for name, expr in _METRICS] + [func.coalesce(func.sum(Run.cost), 0.0).label("cost"), _avg_latency().label("avg_latency_ms")]


def _row_to_metrics(row) -> dict:
    data = {name: int(getattr(row, name) or 0) for name, _ in _METRICS}
    data["cost"] = round(float(row.cost or 0.0), 6)
    data["avg_latency_ms"] = int(round(float(row.avg_latency_ms))) if row.avg_latency_ms is not None else None
    finished = data["success"] + data["failed"]
    data["success_rate"] = round(data["success"] / finished, 4) if finished else None
    return data


def _empty_metrics() -> dict:
    data = {name: 0 for name, _ in _METRICS}
    data.update(cost=0.0, avg_latency_ms=None, success_rate=None)
    return data


def _runs_query(db: Session, since: datetime | None = None, run_type: str | None = None, agent_id: int | None = None, workflow_id: int | None = None):
    """统计基础查询：只扫 runs（成本读快照列 cost，无需 JOIN），带可选过滤。"""
    query = db.query().select_from(Run)
    if since is not None:
        query = query.filter(Run.started_at >= since)
    if run_type:
        query = query.filter(Run.run_type == run_type)
    if agent_id:
        query = query.filter(Run.agent_id == agent_id)
    if workflow_id:
        query = query.filter(Run.workflow_id == workflow_id)
    return query


def _clamp_days(days: int) -> int:
    return max(1, min(days, settings.STATS_MAX_DAYS))


def daily_runs(db: Session, days: int = 30, run_type: str | None = None, agent_id: int | None = None, workflow_id: int | None = None) -> dict:
    """按天的运行数（分状态）、token、成本、平均耗时；没有数据的日期补零，前端直接画图。"""
    days = _clamp_days(days)
    since, labels = _window(days)
    day = func.to_char(func.timezone(settings.REPORT_TIMEZONE, Run.started_at), "YYYY-MM-DD").label("day")
    rows = _runs_query(db, since, run_type, agent_id, workflow_id).add_columns(day, *_metric_columns()).group_by(day).all()
    by_day = {row.day: _row_to_metrics(row) for row in rows}
    return {"days": days, "timezone": settings.REPORT_TIMEZONE, "items": [{"date": label, **by_day.get(label, _empty_metrics())} for label in labels]}


def period_summary(db: Session, days: int, run_type: str | None = None, agent_id: int | None = None, workflow_id: int | None = None) -> dict:
    """时间窗内的汇总指标（一行）。"""
    since, _ = _window(_clamp_days(days))
    row = _runs_query(db, since, run_type, agent_id, workflow_id).add_columns(*_metric_columns()).one()
    return _row_to_metrics(row)


def model_usage(db: Session, days: int = 30, model_id: int | None = None) -> dict:
    """按模型聚合：运行数 / 成功失败 / token / 成本 / 平均耗时（按运行记录上的 model_id 快照，智能体换模型不影响历史归属），
    附引用它的智能体数与熔断状态。用量为 0 的模型也返回。"""
    days = _clamp_days(days)
    since, _ = _window(days)
    query = (
        db.query(ModelConfig.id, ModelConfig.name, ModelConfig.provider, ModelConfig.model_name, ModelConfig.is_enabled, *_metric_columns())
        .select_from(ModelConfig)
        .outerjoin(Run, and_(Run.model_id == ModelConfig.id, Run.started_at >= since))
        .group_by(ModelConfig.id)
        .order_by(func.count(Run.id).desc(), ModelConfig.id)
    )
    if model_id:
        query = query.filter(ModelConfig.id == model_id)
    agents_count = dict(db.query(Agent.model_id, func.count(Agent.id)).group_by(Agent.model_id).all())
    breakers = {b["model_id"]: b for b in breaker.status()}
    items = []
    for row in query.all():
        items.append({
            "model_id": row.id, "name": row.name, "provider": row.provider, "model_name": row.model_name, "is_enabled": row.is_enabled,
            "agents_count": int(agents_count.get(row.id, 0)), "breaker": breakers.get(row.id), **_row_to_metrics(row),
        })
    return {"days": days, "items": items}


def agent_usage(db: Session, days: int = 30, agent_id: int | None = None) -> dict:
    """按智能体聚合：运行指标 + 时间窗内的会话数与消息数 + 最近运行时间。"""
    days = _clamp_days(days)
    since, _ = _window(days)
    query = (
        db.query(Agent.id, Agent.name, Agent.status, Agent.model_id, ModelConfig.name.label("model_name"), func.max(Run.started_at).label("last_run_at"), *_metric_columns())
        .select_from(Agent)
        .outerjoin(ModelConfig, ModelConfig.id == Agent.model_id)
        .outerjoin(Run, and_(Run.agent_id == Agent.id, Run.started_at >= since))
        .group_by(Agent.id, ModelConfig.name)
        .order_by(func.count(Run.id).desc(), Agent.id)
    )
    if agent_id:
        query = query.filter(Agent.id == agent_id)
    conv_q = db.query(Conversation.agent_id, func.count(Conversation.id)).filter(Conversation.created_at >= since)
    msg_q = (
        db.query(Conversation.agent_id, func.count(Message.id))
        .select_from(Message).join(Conversation, Conversation.id == Message.conversation_id)
        .filter(Message.created_at >= since)
    )
    if agent_id:
        conv_q = conv_q.filter(Conversation.agent_id == agent_id)
        msg_q = msg_q.filter(Conversation.agent_id == agent_id)
    conversations = dict(conv_q.group_by(Conversation.agent_id).all())
    messages = dict(msg_q.group_by(Conversation.agent_id).all())
    items = []
    for row in query.all():
        items.append({
            "agent_id": row.id, "name": row.name, "status": row.status, "model_id": row.model_id, "model_name": row.model_name,
            "conversations": int(conversations.get(row.id, 0)), "messages": int(messages.get(row.id, 0)),
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None, **_row_to_metrics(row),
        })
    return {"days": days, "items": items}


def workflow_usage(db: Session, days: int = 30, workflow_id: int | None = None) -> dict:
    """按工作流聚合：运行指标（含待审核数）与最近运行时间。"""
    days = _clamp_days(days)
    since, _ = _window(days)
    query = (
        db.query(Workflow.id, Workflow.name, Workflow.status, func.max(Run.started_at).label("last_run_at"), *_metric_columns())
        .select_from(Workflow)
        .outerjoin(Run, and_(Run.workflow_id == Workflow.id, Run.started_at >= since))
        .group_by(Workflow.id)
        .order_by(func.count(Run.id).desc(), Workflow.id)
    )
    if workflow_id:
        query = query.filter(Workflow.id == workflow_id)
    items = [{
        "workflow_id": row.id, "name": row.name, "status": row.status,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None, **_row_to_metrics(row),
    } for row in query.all()]
    return {"days": days, "items": items}


def overview(db: Session) -> dict:
    """工作台概览：资源计数、今日 / 7 日运行指标、待处理项、降级项、最近运行。一个接口聚齐，前端不必发十几个请求。"""
    resources = {
        "agents": db.query(func.count(Agent.id)).scalar(),
        "published_agents": db.query(func.count(Agent.id)).filter(Agent.status == "published").scalar(),
        "models": db.query(func.count(ModelConfig.id)).scalar(),
        "enabled_models": db.query(func.count(ModelConfig.id)).filter(ModelConfig.is_enabled.is_(True)).scalar(),
        "workflows": db.query(func.count(Workflow.id)).scalar(),
        "knowledge_bases": db.query(func.count(KnowledgeBase.id)).scalar(),
        "documents": db.query(func.count(Document.id)).scalar(),
        "tools": db.query(func.count(Tool.id)).scalar(),
        "prompt_templates": db.query(func.count(PromptTemplate.id)).scalar(),
        "users": db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar(),
        "api_keys": db.query(func.count(ApiKey.id)).filter(ApiKey.is_enabled.is_(True)).scalar(),
        "schedules": db.query(func.count(ScheduledJob.id)).filter(ScheduledJob.is_enabled.is_(True)).scalar(),
    }
    status = system_service.get_system_status(db)
    scheduler = status.get("scheduler") or {}
    today_since, _ = _window(1)
    pending = {
        "awaiting_review": db.query(func.count(Run.id)).filter(Run.status == "awaiting_review").scalar(),
        "running": db.query(func.count(Run.id)).filter(Run.status == "running").scalar(),
        # 超过 1 小时仍 running 的记录通常是进程被杀后没收尾的幽灵记录
        "stuck_running": db.query(func.count(Run.id)).filter(Run.status == "running", Run.started_at < datetime.now(timezone.utc) - timedelta(hours=1)).scalar(),
        "failed_today": db.query(func.count(Run.id)).filter(Run.status == "failed", Run.started_at >= today_since).scalar(),
        "failed_documents": db.query(func.count(Document.id)).filter(Document.status == "failed").scalar(),
        "processing_documents": db.query(func.count(Document.id)).filter(Document.status.in_(("uploading", "parsing", "chunking"))).scalar(),
        "open_breakers": sum(1 for b in status.get("model_breakers", []) if b.get("state") == "open"),
        "unregistered_schedules": max(0, int(scheduler.get("enabled_jobs", 0)) - int(scheduler.get("registered_jobs", 0))),
    }
    return {
        "resources": {k: int(v or 0) for k, v in resources.items()},
        "today": period_summary(db, 1),
        "last_7d": period_summary(db, 7),
        "pending": {k: int(v or 0) for k, v in pending.items()},
        "degraded": status.get("degraded", []),
        "scheduler": scheduler,
        "recent_runs": run_service.recent_runs(db, 8),
    }
