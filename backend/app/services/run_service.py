from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.db.models import Agent, ModelConfig, Run, RunNode

# 运行记录的终态。awaiting_review 不是终态：它不写 finished_at，等待 resume 后再收尾。
FINAL_STATUSES = ("success", "failed", "cancelled")


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


def _calc_cost(db: Session, run: Run):
    if not run.agent_id or not run.token_usage:
        return None
    agent = db.get(Agent, run.agent_id)
    if not agent:
        return None
    model = db.get(ModelConfig, agent.model_id)
    if not model or (model.price_input is None and model.price_output is None):
        return None
    tu = run.token_usage or {}
    prompt = tu.get("prompt_tokens") or 0
    completion = tu.get("completion_tokens") or 0
    cost = prompt / 1000000 * (model.price_input or 0) + completion / 1000000 * (model.price_output or 0)
    return round(cost, 6)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def list_runs(db: Session) -> list[dict]:
    rows = db.query(Run).order_by(Run.id.desc()).limit(200).all()
    return [
        {"id": r.id, "run_type": r.run_type, "agent_id": r.agent_id, "workflow_id": r.workflow_id,
         "status": r.status, "error": r.error, "output": r.output, "latency_ms": r.latency_ms,
         "token_usage": r.token_usage, "cost": _calc_cost(db, r),
         "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at)}
        for r in rows
    ]


def get_run(db: Session, run_id: int) -> dict:
    r = db.get(Run, run_id)
    if r is None:
        raise BizError(404, "运行记录不存在")
    nodes = db.query(RunNode).filter(RunNode.run_id == run_id).order_by(RunNode.id).all()
    return {
        "id": r.id, "run_type": r.run_type, "workflow_id": r.workflow_id, "agent_id": r.agent_id, "status": r.status,
        "input": r.input, "output": r.output, "error": r.error, "token_usage": r.token_usage,
        "cost": _calc_cost(db, r), "latency_ms": r.latency_ms,
        "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
        "nodes": [{"node_id": n.node_id, "node_type": n.node_type, "status": n.status, "error": n.error} for n in nodes],
    }
