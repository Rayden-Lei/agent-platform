"""运行记录（Run）路由：查询对话 / 工作流执行产生的运行记录与汇总。

本模块仅允许 admin / developer 角色访问。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params, time_range
from app.db.models import User
from app.db.session import get_db
from app.services import run_service

router = APIRouter(prefix="/runs", tags=["runs"])
_time_range = time_range

# 运行状态枚举：running 运行中 / success 成功 / failed 失败 / cancelled 取消 / awaiting_review 等待人工审核
RunStatus = Literal["running", "success", "failed", "cancelled", "awaiting_review"]
# 触发来源（runs.source 列）：与 run_service.RUN_SOURCES 一致；debug 是装配页调试
RunSource = Literal["chat", "ui", "api_key", "schedule", "debug", "share"]


class RunBatchIn(BatchIn[Literal["mark_failed"]]):
    """批量处置卡住的运行：action 只接受 "mark_failed"，其余值 422（docs/15 OP-10）。"""


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
    source: RunSource | None = Query(None, description="触发来源"),
    stuck: bool | None = Query(None, description="为 true 时只返回超过阈值仍运行中的（卡住的）运行"),
    started_from: datetime | None = Query(None, description="发起时间下界（含），ISO 8601 带时区"),
    started_to: datetime | None = Query(None, description="发起时间上界（不含），ISO 8601 带时区"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """运行记录列表（分页），可按类型、状态、智能体、工作流、用户、模型、触发来源、是否卡住、发起时间区间过滤；
    sort 可选 id / started_at / finished_at / latency_ms / cost。"""
    started_from, started_to = _time_range(started_from, started_to)
    return run_service.list_runs(db, params, run_type, status, agent_id, workflow_id, user_id, model_id, source,
                                 started_from, started_to, sort, stuck)


# 固定路径必须声明在 /{run_id} 之前，否则 "summary" 会被当成 run_id 解析失败
@router.get("/summary")
def summarize_runs(
    run_type: Literal["chat", "workflow"] | None = Query(None),
    agent_id: int | None = Query(None),
    workflow_id: int | None = Query(None),
    user_id: int | None = Query(None),
    model_id: int | None = Query(None),
    source: RunSource | None = Query(None),
    started_from: datetime | None = Query(None),
    started_to: datetime | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """运行记录汇总统计（按状态计数、token、成本、平均 / P50 / P95 耗时、成功率、耗时分布），过滤条件与列表相同以便联动。"""
    started_from, started_to = _time_range(started_from, started_to)
    return run_service.summarize_runs(db, run_type, agent_id, workflow_id, user_id, model_id, source, started_from, started_to)


# 批量处置同样是固定路径，必须声明在 /{run_id} 之前（否则 "batch" 会被当成 run_id 解析失败）
@router.post("/batch")
def batch_fail_runs(data: RunBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量把卡住的运行标记为失败：逐条独立执行并返回成功与失败清单（docs/15 OP-10）。
    某一条不满足前置条件（未超阈值、已终态）只进 failed 清单，不影响其余条目。"""
    return run_batch(db, data.unique_ids(), lambda run_id: run_service.apply_batch_action(db, run_id, data.action, user))


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询单条运行记录详情（含关联名称与节点日志的输入输出、耗时）。"""
    return run_service.get_run(db, run_id)


@router.post("/{run_id}/mark-failed")
def mark_run_failed(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """把一条卡住的运行标记为失败并回收其工作流检查点（docs/15 OP-10）。

    只允许处置超过 STUCK_RUN_MINUTES 仍 running 的运行：未超阈值 400、已终态 409、不存在 404。
    **本接口只改数据库状态，不会中断仍在执行的线程** —— 页面按钮文案必须写清这一点。
    """
    return run_service.fail_stuck_run(db, run_id, user)
