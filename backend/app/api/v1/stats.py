"""运营统计路由：工作台概览、按天趋势、按模型 / 智能体 / 工作流聚合。

全部只读，admin / developer 可访问；数据在数据库侧聚合，时间窗按 REPORT_TIMEZONE 切天。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


def _days(days: int = Query(30, ge=1, description="最近多少天（含今天），超过上限按上限截断")) -> int:
    return min(days, settings.STATS_MAX_DAYS)


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """工作台概览：资源计数、今日与 7 日运行指标、待处理项、降级项、最近运行。"""
    return stats_service.overview(db)


@router.get("/runs/daily")
def runs_daily(
    days: int = Depends(_days),
    run_type: Literal["chat", "workflow"] | None = Query(None),
    agent_id: int | None = Query(None),
    workflow_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """按天的运行数（分状态）、token、成本、平均耗时；缺失日期补零。"""
    return stats_service.daily_runs(db, days, run_type, agent_id, workflow_id)


@router.get("/runs/summary")
def runs_period_summary(
    days: int = Depends(_days),
    run_type: Literal["chat", "workflow"] | None = Query(None),
    agent_id: int | None = Query(None),
    workflow_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """时间窗内的汇总指标（成功率、平均耗时、token、成本）。"""
    return {"days": days, **stats_service.period_summary(db, days, run_type, agent_id, workflow_id)}


@router.get("/models")
def models_usage(days: int = Depends(_days), model_id: int | None = Query(None), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按模型聚合的用量、成本、成功率、引用智能体数与熔断状态。"""
    return stats_service.model_usage(db, days, model_id)


@router.get("/agents")
def agents_usage(days: int = Depends(_days), agent_id: int | None = Query(None), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按智能体聚合的运行指标、会话数与消息数。"""
    return stats_service.agent_usage(db, days, agent_id)


@router.get("/workflows")
def workflows_usage(days: int = Depends(_days), workflow_id: int | None = Query(None), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按工作流聚合的运行指标与最近运行时间。"""
    return stats_service.workflow_usage(db, days, workflow_id)
