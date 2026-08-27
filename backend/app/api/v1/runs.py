from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import Run, RunNode, User
from app.db.session import get_db

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def list_runs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(Run).order_by(Run.id.desc()).limit(200).all()
    return [
        {"id": r.id, "run_type": r.run_type, "agent_id": r.agent_id, "workflow_id": r.workflow_id,
         "status": r.status, "error": r.error, "output": r.output, "latency_ms": r.latency_ms,
         "token_usage": r.token_usage, "started_at": r.started_at.isoformat() if r.started_at else None}
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
        "output": r.output, "error": r.error, "token_usage": r.token_usage, "latency_ms": r.latency_ms,
        "nodes": [{"node_id": n.node_id, "node_type": n.node_type, "status": n.status, "error": n.error} for n in nodes],
    }
