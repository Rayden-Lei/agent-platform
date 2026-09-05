"""运行记录（Run）路由：查询对话 / 工作流执行产生的运行记录与汇总。

本模块仅允许 admin / developer 角色访问。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params, time_range
from app.db.models import User
from app.db.session import get_db
from app.services import run_service

router = APIRouter(prefix="/runs", tags=["runs"])
_time_range = time_range

# 运行状态枚举：running 运行中 / success 成功 / failed 失败 / cancelled 取消 / awaiting_review 等待人工审核
RunStatus = Literal["running", "success", "failed", "cancelled", "awaiting_review"]


@router.get("")
def list_runs(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    run_type: Literal["chat", "workflow"] | None = Query(None),
    status: RunStatus | None = Query(None),
    agent_id: int | None = Query(None),
    workflow_id: int | None = Query(None),
    user_id: int | None = Query(None),
    model_id: int | None = Query(None),
    source: Literal["chat", "ui", "api_key", "schedule"] | None = Query(None, description="触发来源"),
    started_from: datetime | None = Query(None, description="发起时间下界（含），ISO 8601 带时区"),
    started_to: datetime | None = Query(None, description="发起时间上界（不含），ISO 8601 带时区"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """运行记录列表（分页），可按类型、状态、智能体、工作流、用户、模型、触发来源、发起时间区间过滤；
    sort 可选 id / started_at / finished_at / latency_ms / cost。"""
    started_from, started_to = _time_range(started_from, started_to)
    return run_service.list_runs(db, params, run_type, status, agent_id, workflow_id, user_id, model_id, source, started_from, started_to, sort)


# 固定路径必须声明在 /{run_id} 之前，否则 "summary" 会被当成 run_id 解析失败
@router.get("/summary")
def summarize_runs(
    run_type: Literal["chat", "workflow"] | None = Query(None),
    agent_id: int | None = Query(None),
    workflow_id: int | None = Query(None),
    user_id: int | None = Query(None),
    model_id: int | None = Query(None),
    source: Literal["chat", "ui", "api_key", "schedule"] | None = Query(None),
    started_from: datetime | None = Query(None),
    started_to: datetime | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """运行记录汇总统计（按状态计数、token、成本、平均 / P50 / P95 耗时、成功率、耗时分布），过滤条件与列表相同以便联动。"""
    started_from, started_to = _time_range(started_from, started_to)
    return run_service.summarize_runs(db, run_type, agent_id, workflow_id, user_id, model_id, source, started_from, started_to)


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询单条运行记录详情（含关联名称与节点日志的输入输出、耗时）。"""
    return run_service.get_run(db, run_id)
