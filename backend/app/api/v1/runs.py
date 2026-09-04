"""运行记录（Run）路由：查询对话 / 工作流执行产生的运行记录与汇总。

本模块仅允许 admin / developer 角色访问。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.services import run_service

router = APIRouter(prefix="/runs", tags=["runs"])

# 运行状态枚举：running 运行中 / success 成功 / failed 失败 / cancelled 取消 / awaiting_review 等待人工审核
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
    """运行记录列表（分页），可按类型、状态、智能体、工作流过滤。"""
    return run_service.list_runs(db, params, run_type, status, agent_id, workflow_id)


# 固定路径必须声明在 /{run_id} 之前，否则 "summary" 会被当成 run_id 解析失败
@router.get("/summary")
def summarize_runs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """运行记录汇总统计（如按状态计数）。"""
    return run_service.summarize_runs(db)


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询单条运行记录详情。"""
    return run_service.get_run(db, run_id)
