from datetime import datetime, timezone

from sqlalchemy import BigInteger, cast, func
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import Agent, ModelConfig, Run, RunNode

# 运行记录的终态。awaiting_review 不是终态：它不写 finished_at，等待 resume 后再收尾。
FINAL_STATUSES = ("success", "failed", "cancelled")
RUN_STATUSES = ("running", "success", "failed", "cancelled", "awaiting_review")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_run(db: Session, run_type: str, user_id: int, agent_id: int = None, workflow_id: int = None, input_data: dict = None) -> Run:
    """创建运行记录并写入 started_at。所有产生 Run 的入口（对话/工作流/定时任务）都必须走这里，
    否则 latency_ms 无法计算、监控页耗时永远是 0。"""
    run = Run(
        run_type=run_type, agent_id=agent_id, workflow_id=workflow_id, user_id=user_id,
        status="running", input=input_data or {}, started_at=_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finalize_run(db: Session, run: Run, status: str, output: dict = None, error: str = None, usage: dict = None) -> bool:
    """把运行记录置为终态，并写 finished_at / latency_ms。返回是否实际做了收尾。

    幂等：已处于终态的记录直接返回 False、不做任何改动，保证首次收尾结果不被覆盖
    （典型场景：流式对话已正常 done，随后客户端断开又触发一次取消收尾）。
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
    db.commit()
    return True


def _cost(token_usage: dict, model: ModelConfig | None):
    """按模型单价（元 / 百万 token）折算成本；无用量、无模型或未配单价时为 None。"""
    if not token_usage or model is None or (model.price_input is None and model.price_output is None):
        return None
    prompt = token_usage.get("prompt_tokens") or 0
    completion = token_usage.get("completion_tokens") or 0
    return round(prompt / 1000000 * (model.price_input or 0) + completion / 1000000 * (model.price_output or 0), 6)


def _cost_by_run(db: Session, runs: list) -> dict:
    """一页运行记录的成本：智能体、模型各批量查一次，内存装配；不逐行查库。"""
    agent_ids = {r.agent_id for r in runs if r.agent_id}
    agents = {a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()} if agent_ids else {}
    model_ids = {a.model_id for a in agents.values()}
    models = {m.id: m for m in db.query(ModelConfig).filter(ModelConfig.id.in_(model_ids)).all()} if model_ids else {}
    costs = {}
    for r in runs:
        agent = agents.get(r.agent_id) if r.agent_id else None
        costs[r.id] = _cost(r.token_usage, models.get(agent.model_id) if agent else None)
    return costs


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _run_dict(r: Run, cost) -> dict:
    """运行记录 → 对外字典（含折算成本）。"""
    return {
        "id": r.id, "run_type": r.run_type, "agent_id": r.agent_id, "workflow_id": r.workflow_id,
        "status": r.status, "error": r.error, "output": r.output, "latency_ms": r.latency_ms,
        "token_usage": r.token_usage, "cost": cost,
        "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
    }


def list_runs(db: Session, params: PageParams, run_type: str = None, status: str = None,
              agent_id: int = None, workflow_id: int = None) -> dict:
    """分页查询运行记录：run_type / status / agent_id / workflow_id 均为可选精确过滤；
    返回前为一页数据批量装配成本（智能体、模型各查一次，不在循环内查库）。"""
    query = db.query(Run)
    if run_type:
        query = query.filter(Run.run_type == run_type)
    if status:
        query = query.filter(Run.status == status)
    if agent_id:
        query = query.filter(Run.agent_id == agent_id)
    if workflow_id:
        query = query.filter(Run.workflow_id == workflow_id)
    page = paginate(query.order_by(Run.id.desc()), params)
    costs = _cost_by_run(db, page["items"])
    page["items"] = [_run_dict(r, costs[r.id]) for r in page["items"]]
    return page


def summarize_runs(db: Session) -> dict:
    """运行记录页顶部统计：各状态数量、总 token、总成本，全部在数据库聚合。"""
    by_status = dict(db.query(Run.status, func.count(Run.id)).group_by(Run.status).all())
    total_tokens = db.query(
        func.coalesce(func.sum(func.coalesce(cast(Run.token_usage["total_tokens"].astext, BigInteger), 0)), 0)
    ).scalar()
    prompt = func.coalesce(cast(Run.token_usage["prompt_tokens"].astext, BigInteger), 0)
    completion = func.coalesce(cast(Run.token_usage["completion_tokens"].astext, BigInteger), 0)
    cost_expr = (prompt * func.coalesce(ModelConfig.price_input, 0.0) + completion * func.coalesce(ModelConfig.price_output, 0.0)) / 1000000.0
    total_cost = (
        db.query(func.coalesce(func.sum(cost_expr), 0.0))
        .select_from(Run)
        .join(Agent, Agent.id == Run.agent_id)
        .join(ModelConfig, ModelConfig.id == Agent.model_id)
        .scalar()
    )
    summary = {s: int(by_status.get(s, 0)) for s in RUN_STATUSES}
    summary["total"] = sum(summary.values())
    summary["total_tokens"] = int(total_tokens or 0)
    summary["total_cost"] = round(float(total_cost or 0.0), 6)
    return summary


def get_run(db: Session, run_id: int) -> dict:
    """取单条运行详情：含输入、折算成本与各节点执行结果，不存在抛 BizError(404)。"""
    r = db.get(Run, run_id)
    if r is None:
        raise BizError(404, "运行记录不存在")
    agent = db.get(Agent, r.agent_id) if r.agent_id else None
    model = db.get(ModelConfig, agent.model_id) if agent else None
    nodes = db.query(RunNode).filter(RunNode.run_id == run_id).order_by(RunNode.id).all()
    return {
        **_run_dict(r, _cost(r.token_usage, model)),
        "input": r.input,
        "nodes": [{"node_id": n.node_id, "node_type": n.node_type, "status": n.status, "error": n.error} for n in nodes],
    }
