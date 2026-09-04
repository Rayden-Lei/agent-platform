"""定时任务路由：把工作流绑定到 cron 表达式定时触发。

本模块仅允许 admin / developer 角色访问。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.services import schedule_service

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ScheduleIn(BaseModel):
    """定时任务请求体：workflow_id 指定要运行的工作流；cron 为调度表达式；input 为工作流输入。"""

    name: str
    workflow_id: int
    cron: str
    input: dict = {}


@router.get("")
def list_schedules(params: PageParams = Depends(page_params), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """定时任务列表（分页）。"""
    return schedule_service.list_schedules(db, params)


@router.post("")
def create_schedule(data: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建定时任务。"""
    return schedule_service.create_schedule(db, data, user)


@router.post("/{schedule_id}/toggle")
def toggle_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """启用 / 停用定时任务（开关切换）。"""
    return schedule_service.toggle_schedule(db, schedule_id)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除定时任务。"""
    schedule_service.delete_schedule(db, schedule_id)
    return {"code": 0, "message": "ok"}
