"""定时任务路由：把工作流绑定到 cron 表达式定时触发；支持编辑、立即执行与批量启停 / 删除。

本模块仅允许 admin / developer 角色访问。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.core.scheduler import is_valid_cron
from app.db.models import User
from app.db.session import get_db
from app.services import schedule_service

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ScheduleIn(BaseModel):
    """定时任务请求体：workflow_id 指定要运行的工作流；cron 为五段 crontab 表达式（非法 422）；input 为工作流输入。"""

    name: str = Field(min_length=1, max_length=128)
    workflow_id: int
    cron: str = Field(min_length=1, max_length=64)
    input: dict = Field(default_factory=dict)

    @field_validator("cron")
    @classmethod
    def _check_cron(cls, value: str) -> str:
        value = value.strip()
        if not is_valid_cron(value):
            raise ValueError(f"cron 表达式非法：{value!r}，格式为「分 时 日 月 周」，如 */5 * * * *")
        return value


class ScheduleBatchIn(BatchIn):
    action: Literal["enable", "disable", "delete"]


@router.get("")
def list_schedules(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    workflow_id: int | None = Query(None),
    is_enabled: bool | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """定时任务列表（分页），可按名称、工作流、启用状态过滤；sort 可选 id / name / last_run_at / created_at；
    附工作流名、创建人、下次触发时间、最近一次运行。"""
    return schedule_service.list_schedules(db, params, q, workflow_id, is_enabled, sort)


@router.post("")
def create_schedule(data: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建定时任务；工作流不存在 404。"""
    return schedule_service.create_schedule(db, data, user)


# 固定路径必须声明在 /{schedule_id} 之前
@router.post("/batch")
def batch_schedules(data: ScheduleBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量启用 / 停用 / 删除：逐条独立执行并返回成功与失败清单。"""
    return run_batch(db, data.unique_ids(), lambda schedule_id: schedule_service.apply_batch_action(db, schedule_id, data.action))


@router.get("/{schedule_id}")
def get_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """定时任务详情。"""
    return schedule_service.get_schedule_detail(db, schedule_id)


@router.put("/{schedule_id}")
def update_schedule(schedule_id: int, data: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """编辑定时任务（整体覆盖）；启用中的任务按新配置重新注册。"""
    return schedule_service.update_schedule(db, schedule_id, data)


@router.post("/{schedule_id}/toggle")
def toggle_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """启用 / 停用定时任务（开关切换）。"""
    return schedule_service.toggle_schedule(db, schedule_id)


@router.post("/{schedule_id}/run")
def run_schedule_now(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """立即执行一次（异步，在调度器线程里跑）；结果去运行记录页看。"""
    return schedule_service.run_now(db, schedule_id)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除定时任务。"""
    schedule_service.delete_schedule(db, schedule_id)
    return {"code": 0, "message": "ok"}
