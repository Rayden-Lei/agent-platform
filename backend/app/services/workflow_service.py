import asyncio
import uuid

from langgraph.types import Command
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.db.models import Agent, Run, Workflow
from app.workflow.engine import build_workflow


def list_workflows(db: Session) -> list[dict]:
    rows = db.query(Workflow).order_by(Workflow.id).all()
    return [{"id": w.id, "name": w.name, "description": w.description, "status": w.status, "version": w.version} for w in rows]


def create_workflow(db: Session, data, user) -> dict:
    w = Workflow(name=data.name, description=data.description, graph=data.graph, created_by=user.id)
    db.add(w)
    db.commit()
    db.refresh(w)
    return {"id": w.id, "name": w.name, "description": w.description, "status": w.status, "version": w.version}


def get_workflow(db: Session, workflow_id: int) -> Workflow:
    w = db.get(Workflow, workflow_id)
    if w is None:
        raise BizError(404, "工作流不存在")
    return w


def get_workflow_detail(db: Session, workflow_id: int) -> dict:
    w = get_workflow(db, workflow_id)
    return {"id": w.id, "name": w.name, "description": w.description, "graph": w.graph, "status": w.status, "version": w.version}


def update_workflow(db: Session, workflow_id: int, data) -> dict:
    w = get_workflow(db, workflow_id)
    w.name = data.name
    w.description = data.description
    w.graph = data.graph
    w.version = (w.version or 0) + 1
    db.commit()
    db.refresh(w)
    return {"id": w.id, "name": w.name, "version": w.version}


def delete_workflow(db: Session, workflow_id: int) -> None:
    w = get_workflow(db, workflow_id)
    # agents.workflow_id 为 RESTRICT，删除前给出友好提示
    ref_count = db.query(Agent).filter(Agent.workflow_id == workflow_id).count()
    if ref_count:
        raise BizError(409, f"该工作流已被 {ref_count} 个智能体引用，无法删除")
    # runs / run_nodes / conversations / workflow_nodes / scheduled_jobs 由数据库外键 CASCADE 级联删除
    db.delete(w)
    db.commit()


def _interrupt_value(result: dict):
    iv = result.get("__interrupt__")
    if iv:
        first = iv[0]
        return getattr(first, "value", first)
    return None


async def test_run_workflow(graph: dict, input_text: str) -> dict:
    """编辑器内测试运行：用当前图直接执行，不落库。"""
    try:
        g = build_workflow(graph)
        thread_id = "test-" + uuid.uuid4().hex[:12]
        result = await asyncio.to_thread(g.invoke, {"input": input_text, "steps": []}, {"configurable": {"thread_id": thread_id}})
        iv = _interrupt_value(result)
        if iv is not None:
            return {"status": "awaiting_review", "interrupt": iv, "steps": result.get("steps", [])}
        return {"status": "success", "output": result.get("output"), "steps": result.get("steps", [])}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def run_workflow(db: Session, workflow_id: int, input_text: str, user) -> dict:
    w = get_workflow(db, workflow_id)
    run = Run(run_type="workflow", workflow_id=workflow_id, user_id=user.id, status="running", input={"input": input_text})
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        graph = build_workflow(w.graph, run_id=run.id)
        result = await asyncio.to_thread(graph.invoke, {"input": input_text, "steps": []}, {"configurable": {"thread_id": str(run.id)}})
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


async def resume_workflow(db: Session, workflow_id: int, run_id: int, decision: dict) -> dict:
    w = get_workflow(db, workflow_id)
    run = db.get(Run, run_id)
    if run is None or run.workflow_id != workflow_id:
        raise BizError(404, "运行记录不存在")
    if run.status != "awaiting_review":
        raise BizError(400, "该运行不在待审核状态")

    try:
        graph = build_workflow(w.graph, run_id=run.id)
        result = await asyncio.to_thread(graph.invoke, Command(resume=decision), {"configurable": {"thread_id": str(run_id)}})
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


def list_workflow_runs(db: Session, workflow_id: int) -> list[dict]:
    get_workflow(db, workflow_id)
    rows = db.query(Run).filter(Run.workflow_id == workflow_id).order_by(Run.id.desc()).all()
    return [{"id": r.id, "status": r.status, "error": r.error, "output": r.output} for r in rows]
