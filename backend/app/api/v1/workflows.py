from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import Run, User, Workflow
from app.db.session import SessionLocal, get_db
from app.workflow.engine import build_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowIn(BaseModel):
    name: str
    description: str = ""
    graph: dict


class RunIn(BaseModel):
    input: str = ""


@router.get("")
def list_workflows(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(Workflow).order_by(Workflow.id).all()
    return [{"id": w.id, "name": w.name, "description": w.description, "status": w.status, "version": w.version} for w in rows]


@router.post("")
def create_workflow(data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    w = Workflow(name=data.name, description=data.description, graph=data.graph, created_by=user.id)
    db.add(w)
    db.commit()
    db.refresh(w)
    return {"id": w.id, "name": w.name, "description": w.description, "status": w.status, "version": w.version}


@router.get("/{workflow_id}")
def get_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    w = db.get(Workflow, workflow_id)
    if w is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"id": w.id, "name": w.name, "description": w.description, "graph": w.graph, "status": w.status, "version": w.version}


@router.put("/{workflow_id}")
def update_workflow(workflow_id: int, data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    w = db.get(Workflow, workflow_id)
    if w is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    w.name = data.name
    w.description = data.description
    w.graph = data.graph
    w.version = (w.version or 0) + 1
    db.commit()
    db.refresh(w)
    return {"id": w.id, "name": w.name, "version": w.version}


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    w = db.get(Workflow, workflow_id)
    if w is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    db.delete(w)
    db.commit()
    return {"code": 0, "message": "ok"}


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: int, data: RunIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    w = db.get(Workflow, workflow_id)
    if w is None:
        raise HTTPException(status_code=404, detail="工作流不存在")

    run = Run(run_type="workflow", workflow_id=workflow_id, user_id=user.id, status="running", input={"input": data.input})
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        graph = build_workflow(w.graph, run_id=run.id)
        result = await graph.ainvoke({"input": data.input, "steps": []})
        run.status = "success"
        run.output = {"output": result.get("output"), "steps": result.get("steps", [])}
        db.commit()
        return {"run_id": run.id, "status": "success", "output": result.get("output"), "steps": result.get("steps", [])}
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        db.commit()
        return {"run_id": run.id, "status": "failed", "error": str(e)}


@router.get("/{workflow_id}/runs")
def list_runs(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(Run).filter(Run.workflow_id == workflow_id).order_by(Run.id.desc()).all()
    return [{"id": r.id, "status": r.status, "error": r.error, "output": r.output} for r in rows]