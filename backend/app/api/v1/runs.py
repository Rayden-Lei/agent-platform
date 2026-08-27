from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import Agent, ModelConfig, Run, RunNode, User
from app.db.session import get_db

router = APIRouter(prefix="/runs", tags=["runs"])


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


@router.get("")
def list_runs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(Run).order_by(Run.id.desc()).limit(200).all()
    return [
        {"id": r.id, "run_type": r.run_type, "agent_id": r.agent_id, "workflow_id": r.workflow_id,
         "status": r.status, "error": r.error, "output": r.output, "latency_ms": r.latency_ms,
         "token_usage": r.token_usage, "cost": _calc_cost(db, r), "started_at": r.started_at.isoformat() if r.started_at else None}
        for r in rows
    ]


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    r = db.get(Run, run_id)
    if r is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    nodes = db.query(RunNode).filter(RunNode.run_id == run_id).order_by(RunNode.id).all()
    return {
        "id": r.id, "run_type": r.run_type, "status": r.status, "input": r.input,
        "output": r.output, "error": r.error, "token_usage": r.token_usage, "cost": _calc_cost(db, r), "latency_ms": r.latency_ms,
        "nodes": [{"node_id": n.node_id, "node_type": n.node_type, "status": n.status, "error": n.error} for n in nodes],
    }