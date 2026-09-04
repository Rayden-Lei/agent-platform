from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.services import workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowIn(BaseModel):
    name: str
    description: str = ""
    graph: dict


class RunIn(BaseModel):
    input: str = ""


class TestRunIn(BaseModel):
    graph: dict
    input: str = ""


class ResumeIn(BaseModel):
    decision: dict = {}


@router.get("")
def list_workflows(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return workflow_service.list_workflows(db)


@router.post("")
def create_workflow(data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return workflow_service.create_workflow(db, data, user)


@router.post("/test-run")
async def test_run_workflow(data: TestRunIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return await workflow_service.test_run_workflow(data.graph, data.input, role=user.role)


@router.get("/{workflow_id}")
def get_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return workflow_service.get_workflow_detail(db, workflow_id)


@router.put("/{workflow_id}")
def update_workflow(workflow_id: int, data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return workflow_service.update_workflow(db, workflow_id, data)


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    workflow_service.delete_workflow(db, workflow_id)
    return {"code": 0, "message": "ok"}


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: int, data: RunIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    return await workflow_service.run_workflow(db, workflow_id, data.input, user)


@router.post("/{workflow_id}/runs/{run_id}/resume")
async def resume_workflow(workflow_id: int, run_id: int, data: ResumeIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    return await workflow_service.resume_workflow(db, workflow_id, run_id, data.decision)


@router.get("/{workflow_id}/runs")
def list_runs(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return workflow_service.list_workflow_runs(db, workflow_id)
