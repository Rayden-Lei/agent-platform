from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.core.scheduler import add_schedule_job, remove_schedule_job
from app.db.models import ScheduledJob, User


def list_schedules(db: Session, params: PageParams) -> dict:
    """分页列出定时任务，按 ID 倒序。"""
    return paginate(db.query(ScheduledJob).order_by(ScheduledJob.id.desc()), params, lambda s: {
        "id": s.id, "name": s.name, "workflow_id": s.workflow_id, "cron": s.cron, "input": s.input,
        "is_enabled": s.is_enabled, "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
    })


def create_schedule(db: Session, data, user: User) -> dict:
    """新建定时任务：落库后立即注册到调度器，注册失败会影响实际触发。"""
    sj = ScheduledJob(name=data.name, workflow_id=data.workflow_id, user_id=user.id, cron=data.cron, input=data.input)
    db.add(sj)
    db.commit()
    db.refresh(sj)
    add_schedule_job(sj)
    return {"id": sj.id, "name": sj.name, "cron": sj.cron, "is_enabled": sj.is_enabled}


def toggle_schedule(db: Session, schedule_id: int) -> dict:
    """启用/停用定时任务，并同步调度器的注册/注销，保证库中状态与调度器一致。"""
    s = db.get(ScheduledJob, schedule_id)
    if s is None:
        raise BizError(404, "定时任务不存在")
    s.is_enabled = not s.is_enabled
    db.commit()
    if s.is_enabled:
        add_schedule_job(s)
    else:
        remove_schedule_job(s.id)
    return {"id": s.id, "is_enabled": s.is_enabled}


def delete_schedule(db: Session, schedule_id: int) -> None:
    """删除定时任务：先从调度器移除，再删库记录。"""
    s = db.get(ScheduledJob, schedule_id)
    if s is None:
        raise BizError(404, "定时任务不存在")
    remove_schedule_job(s.id)
    db.delete(s)
    db.commit()
