from datetime import datetime, timezone

from sqlalchemy import BigInteger, case, cast, func
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.models import Agent, ModelConfig, Run, RunNode, User, Workflow

# 运行记录的终态。awaiting_review 不是终态：它不写 finished_at，等待 resume 后再收尾。
FINAL_STATUSES = ("success", "failed", "cancelled")
RUN_STATUSES = ("running", "success", "failed", "cancelled", "awaiting_review")
# 触发来源（写在 input.source）：对话 / 界面运行工作流 / API Key 运行工作流 / 定时任务
RUN_SOURCES = ("chat", "ui", "api_key", "schedule")

# 列表排序白名单（字段名不能拼进 SQL）
SORTABLE = {"id": Run.id, "started_at": Run.started_at, "finished_at": Run.finished_at, "latency_ms": Run.latency_ms, "cost": Run.cost}
# 耗时分布的桶边界（毫秒），与前端"耗时分布"图一致
LATENCY_BUCKETS = [(0, 1000, "<1s"), (1000, 3000, "1-3s"), (3000, 10000, "3-10s"), (10000, 30000, "10-30s"), (30000, 60000, "30-60s"), (60000, None, ">60s")]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_run(db: Session, run_type: str, user_id: int, agent_id: int = None, workflow_id: int = None,
               input_data: dict = None, model_id: int = None, conversation_id: int = None) -> Run:
    """创建运行记录并写入 started_at。所有产生 Run 的入口（对话/工作流/定时任务）都必须走这里，
    否则 latency_ms 无法计算、监控页耗时永远是 0。model_id / conversation_id 是统计与追溯用的快照。"""
    run = Run(
        run_type=run_type, agent_id=agent_id, workflow_id=workflow_id, user_id=user_id,
        model_id=model_id, conversation_id=conversation_id,
        status="running", input=input_data or {}, started_at=_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finalize_run(db: Session, run: Run, status: str, output: dict = None, error: str = None, usage: dict = None) -> bool:
    """把运行记录置为终态，并写 finished_at / latency_ms / cost 快照。返回是否实际做了收尾。

    幂等：已处于终态的记录直接返回 False、不做任何改动，保证首次收尾结果不被覆盖
    （典型场景：流式对话已正常 done，随后客户端断开又触发一次取消收尾）。
    成本按收尾时的模型单价折算后落库，之后改单价不追溯，趋势图不会被重写。
    """
    if status not in FINAL_STATUSES:
        raise ValueError(f"finalize_run 只接受终态 {FINAL_STATUSES}，收到: {status}")
    if run.status in FINAL_STATUSES:
        return False
    run.status = status
    if output is not None:
        run.output = output
    if usage is not None:
        run.token_usage = usage
    if error:
        run.error = str(error)[:2000]
    run.finished_at = _now()
    if run.started_at:
        run.latency_ms = max(0, int((run.finished_at - run.started_at).total_seconds() * 1000))
    if run.token_usage and run.model_id:
        run.cost = _cost(run.token_usage, db.get(ModelConfig, run.model_id))
    db.commit()
    return True


def _cost(token_usage: dict, model: ModelConfig | None):
    """按模型单价（元 / 百万 token）折算成本；无用量、无模型或未配单价时为 None。"""
    if not token_usage or model is None or (model.price_input is None and model.price_output is None):
        return None
    prompt = token_usage.get("prompt_tokens") or 0
    completion = token_usage.get("completion_tokens") or 0
    return round(prompt / 1000000 * (model.price_input or 0) + completion / 1000000 * (model.price_output or 0), 6)


class _Related:
    """一页运行记录的关联名称（智能体、模型、工作流、用户）：各批量查一次，内存装配；不逐行查库。"""

    def __init__(self, db: Session, runs: list):
        agent_ids = {r.agent_id for r in runs if r.agent_id}
        model_ids = {r.model_id for r in runs if r.model_id}
        workflow_ids = {r.workflow_id for r in runs if r.workflow_id}
        user_ids = {r.user_id for r in runs if r.user_id}
        self.agents = dict(db.query(Agent.id, Agent.name).filter(Agent.id.in_(agent_ids)).all()) if agent_ids else {}
        self.models = dict(db.query(ModelConfig.id, ModelConfig.name).filter(ModelConfig.id.in_(model_ids)).all()) if model_ids else {}
        self.workflows = dict(db.query(Workflow.id, Workflow.name).filter(Workflow.id.in_(workflow_ids)).all()) if workflow_ids else {}
        self.users = dict(db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()) if user_ids else {}

    def to_dict(self, run: Run) -> dict:
        return {
            **_run_dict(run),
            "agent_name": self.agents.get(run.agent_id) if run.agent_id else None,
            "model_name": self.models.get(run.model_id) if run.model_id else None,
            "workflow_name": self.workflows.get(run.workflow_id) if run.workflow_id else None,
            "username": self.users.get(run.user_id) if run.user_id else None,
        }


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _run_dict(r: Run) -> dict:
    """运行记录 → 对外字典。source / schedule_id 从 input 里取出来单列，方便追溯触发来源。"""
    payload = r.input or {}
    return {
        "id": r.id, "run_type": r.run_type, "agent_id": r.agent_id, "workflow_id": r.workflow_id, "user_id": r.user_id,
        "model_id": r.model_id, "conversation_id": r.conversation_id,
        "source": payload.get("source") or ("chat" if r.run_type == "chat" else ("schedule" if payload.get("scheduled") else None)),
        "schedule_id": payload.get("schedule_id"),
        "status": r.status, "error": r.error, "output": r.output, "latency_ms": r.latency_ms,
        "token_usage": r.token_usage, "cost": r.cost,
        "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
    }


def _filtered(db: Session, run_type: str = None, status: str = None, agent_id: int = None, workflow_id: int = None,
              user_id: int = None, model_id: int = None, source: str = None,
              started_from: datetime = None, started_to: datetime = None):
    """列表与汇总共用的过滤条件：精确过滤 + 发起时间左闭右开区间。"""
    query = db.query(Run)
    if run_type:
        query = query.filter(Run.run_type == run_type)
    if status:
        query = query.filter(Run.status == status)
    if agent_id:
        query = query.filter(Run.agent_id == agent_id)
    if workflow_id:
        query = query.filter(Run.workflow_id == workflow_id)
    if user_id:
        query = query.filter(Run.user_id == user_id)
    if model_id:
        query = query.filter(Run.model_id == model_id)
    if source:
        query = query.filter(Run.input["source"].astext == source)
    if started_from is not None:
        query = query.filter(Run.started_at >= started_from)
    if started_to is not None:
        query = query.filter(Run.started_at < started_to)
    return query


def list_runs(db: Session, params: PageParams, run_type: str = None, status: str = None,
              agent_id: int = None, workflow_id: int = None, user_id: int = None, model_id: int = None, source: str = None,
              started_from: datetime = None, started_to: datetime = None, sort: SortParams = None) -> dict:
    """分页查询运行记录：精确过滤 + 时间区间 + 白名单排序（默认 id 倒序）；
    返回前为一页数据批量装配关联名称（智能体、模型、工作流、用户各查一次，不在循环内查库）。"""
    query = _filtered(db, run_type, status, agent_id, workflow_id, user_id, model_id, source, started_from, started_to)
    page = paginate(apply_sort(query, sort, SORTABLE, [Run.id.desc()]), params)
    related = _Related(db, page["items"])
    page["items"] = [related.to_dict(r) for r in page["items"]]
    return page


def recent_runs(db: Session, limit: int = 10) -> list[dict]:
    """最近的 N 条运行（工作台用），带关联名称。"""
    runs = db.query(Run).order_by(Run.id.desc()).limit(limit).all()
    related = _Related(db, runs)
    return [related.to_dict(r) for r in runs]


def summarize_runs(db: Session, run_type: str = None, agent_id: int = None, workflow_id: int = None,
                   user_id: int = None, model_id: int = None, source: str = None,
                   started_from: datetime = None, started_to: datetime = None) -> dict:
    """运行记录页顶部统计：各状态数量、总 token、总成本、平均 / P50 / P95 耗时、成功率、耗时分布，
    全部在数据库聚合，随列表筛选联动。成本读收尾时的快照列，不再实时折算。"""
    base = _filtered(db, run_type, None, agent_id, workflow_id, user_id, model_id, source, started_from, started_to)
    by_status = dict(base.with_entities(Run.status, func.count(Run.id)).group_by(Run.status).all())
    tokens_row = base.with_entities(
        func.coalesce(func.sum(func.coalesce(cast(Run.token_usage["prompt_tokens"].astext, BigInteger), 0)), 0),
        func.coalesce(func.sum(func.coalesce(cast(Run.token_usage["completion_tokens"].astext, BigInteger), 0)), 0),
        func.coalesce(func.sum(func.coalesce(cast(Run.token_usage["total_tokens"].astext, BigInteger), 0)), 0),
        func.coalesce(func.sum(Run.cost), 0.0),
    ).one()
    finished = base.filter(Run.finished_at.isnot(None))
    latency_row = finished.with_entities(
        func.avg(Run.latency_ms),
        func.percentile_cont(0.5).within_group(Run.latency_ms),
        func.percentile_cont(0.95).within_group(Run.latency_ms),
    ).one()
    bucket_rows = finished.with_entities(
        *[func.count(case((_bucket_condition(low, high), 1), else_=None)) for low, high, _ in LATENCY_BUCKETS]
    ).one()
    summary = {s: int(by_status.get(s, 0)) for s in RUN_STATUSES}
    summary["total"] = sum(summary.values())
    summary["prompt_tokens"] = int(tokens_row[0] or 0)
    summary["completion_tokens"] = int(tokens_row[1] or 0)
    summary["total_tokens"] = int(tokens_row[2] or 0)
    summary["total_cost"] = round(float(tokens_row[3] or 0.0), 6)
    summary["avg_latency_ms"] = int(round(float(latency_row[0]))) if latency_row[0] is not None else None
    summary["p50_latency_ms"] = int(round(float(latency_row[1]))) if latency_row[1] is not None else None
    summary["p95_latency_ms"] = int(round(float(latency_row[2]))) if latency_row[2] is not None else None
    done = summary["success"] + summary["failed"]
    summary["success_rate"] = round(summary["success"] / done, 4) if done else None
    summary["latency_buckets"] = [
        {"label": label, "from_ms": low, "to_ms": high, "count": int(count or 0)}
        for (low, high, label), count in zip(LATENCY_BUCKETS, bucket_rows)
    ]
    return summary


def _bucket_condition(low: int, high: int | None):
    return (Run.latency_ms >= low) if high is None else ((Run.latency_ms >= low) & (Run.latency_ms < high))


def _node_dict(n: RunNode) -> dict:
    """节点日志：输入输出是引擎截断到 500 字符的文本快照（{"data": "..."}），耗时由起止时间算。"""
    duration = int((n.finished_at - n.started_at).total_seconds() * 1000) if n.started_at and n.finished_at else None
    return {
        "id": n.id, "node_id": n.node_id, "node_type": n.node_type, "status": n.status, "error": n.error,
        "input": (n.input or {}).get("data"), "output": (n.output or {}).get("data"),
        "started_at": _iso(n.started_at), "finished_at": _iso(n.finished_at), "duration_ms": duration,
    }


def get_run(db: Session, run_id: int) -> dict:
    """取单条运行详情：含输入、关联名称与各节点执行结果（输入输出快照、起止时间、耗时），不存在抛 BizError(404)。"""
    r = db.get(Run, run_id)
    if r is None:
        raise BizError(404, "运行记录不存在")
    related = _Related(db, [r])
    nodes = db.query(RunNode).filter(RunNode.run_id == run_id).order_by(RunNode.id).all()
    return {**related.to_dict(r), "input": r.input, "nodes": [_node_dict(n) for n in nodes]}
