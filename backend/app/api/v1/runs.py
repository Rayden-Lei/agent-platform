from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.services import run_service

router = APIRouter(prefix="/runs", tags=["runs"])

RunStatus = Literal["running", "success", "failed", "cancelled", "awaiting_review"]


@router.get("")
def list_runs(
    params: PageParams = Depends(page_params),
    run_type: Literal["chat", "workflow"] | None = Query(None),
    status: RunStatus | None = Query(None),
    agent_id: int | None = Query(None),
    workflow_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    return run_service.list_runs(db, params, run_type, status, agent_id, workflow_id)


# 固定路径必须声明在 /{run_id} 之前，否则 "summary" 会被当成 run_id 解析失败
@router.get("/summary")
def summarize_runs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return run_service.summarize_runs(db)


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return run_service.get_run(db, run_id)
