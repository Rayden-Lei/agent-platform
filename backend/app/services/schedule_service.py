from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.scheduler import add_schedule_job, remove_schedule_job
from app.db.models import ScheduledJob, User


def list_schedules(db: Session) -> list[dict]:
    rows = db.query(ScheduledJob).order_by(ScheduledJob.id.desc()).all()
    return [
        {"id": s.id, "name": s.name, "workflow_id": s.workflow_id, "cron": s.cron, "input": s.input,
         "is_enabled": s.is_enabled, "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
        for s in rows
    ]


def create_schedule(db: Session, data, user: User) -> dict:
    sj = ScheduledJob(name=data.name, workflow_id=data.workflow_id, user_id=user.id, cron=data.cron, input=data.input)
    db.add(sj)
    db.commit()
    db.refresh(sj)
    add_schedule_job(sj)
    return {"id": sj.id, "name": sj.name, "cron": sj.cron, "is_enabled": sj.is_enabled}


def toggle_schedule(db: Session, schedule_id: int) -> dict:
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
    s = db.get(ScheduledJob, schedule_id)
    if s is None:
        raise BizError(404, "定时任务不存在")
    remove_schedule_job(s.id)
    db.delete(s)
    db.commit()
