import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import Run, RunNode, User, Workflow
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


class TestRunIn(BaseModel):
    graph: dict
    input: str = ""


@router.post("/test-run")
async def test_run_workflow(data: TestRunIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """编辑器内测试运行：用当前图直接执行，不落库。"""
    try:
        graph = build_workflow(data.graph)
        thread_id = "test-" + uuid.uuid4().hex[:12]
        result = await asyncio.to_thread(graph.invoke, {"input": data.input, "steps": []}, {"configurable": {"thread_id": thread_id}})
        if result.get("__interrupt__"):
            return {"status": "awaiting_review", "interrupt": result["__interrupt__"][0].value, "steps": result.get("steps", [])}
        return {"status": "success", "output": result.get("output"), "steps": result.get("steps", [])}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


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
    run_ids = [r.id for r in db.query(Run).filter(Run.workflow_id == workflow_id).all()]
    if run_ids:
        db.query(RunNode).filter(RunNode.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(Run).filter(Run.workflow_id == workflow_id).delete(synchronize_session=False)
    db.delete(w)
    db.commit()
    return {"code": 0, "message": "ok"}


def _interrupt_value(result: dict):
    iv = result.get("__interrupt__")
    if iv:
        first = iv[0]
        return getattr(first, "value", first)
    return None


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
        result = await asyncio.to_thread(graph.invoke, {"input": data.input, "steps": []}, {"configurable": {"thread_id": str(run.id)}})
        iv = _interrupt_value(result)
        if iv is not None:
            run.status = "awaiting_review"
            run.output = {"interrupt": iv, "steps": result.get("steps", [])}
            db.commit()
            return {"run_id": run.id, "status": "awaiting_review", "interrupt": iv, "steps": result.get("steps", [])}
        run.status = "success"
        run.output = {"output": result.get("output"), "steps": result.get("steps", [])}
        db.commit()
        return {"run_id": run.id, "status": "success", "output": result.get("output"), "steps": result.get("steps", [])}
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        db.commit()
        return {"run_id": run.id, "status": "failed", "error": str(e)}


class ResumeIn(BaseModel):
    decision: dict = {}


@router.post("/{workflow_id}/runs/{run_id}/resume")
async def resume_workflow(workflow_id: int, run_id: int, data: ResumeIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    w = db.get(Workflow, workflow_id)
    if w is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    run = db.get(Run, run_id)
    if run is None or run.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status != "awaiting_review":
        raise HTTPException(status_code=400, detail="该运行不在待审核状态")

    try:
        graph = build_workflow(w.graph, run_id=run.id)
        result = await asyncio.to_thread(graph.invoke, Command(resume=data.decision), {"configurable": {"thread_id": str(run_id)}})
        iv = _interrupt_value(result)
        if iv is not None:
            run.output = {"interrupt": iv, "steps": result.get("steps", [])}
            db.commit()
            return {"run_id": run.id, "status": "awaiting_review", "interrupt": iv, "steps": result.get("steps", [])}
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