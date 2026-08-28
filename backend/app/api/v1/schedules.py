from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.scheduler import add_schedule_job, remove_schedule_job
from app.db.models import ScheduledJob, User
from app.db.session import get_db

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ScheduleIn(BaseModel):
    name: str
    workflow_id: int
    cron: str
    input: dict = {}


@router.get("")
def list_schedules(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(ScheduledJob).order_by(ScheduledJob.id.desc()).all()
    return [
        {"id": s.id, "name": s.name, "workflow_id": s.workflow_id, "cron": s.cron, "input": s.input,
         "is_enabled": s.is_enabled, "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
        for s in rows
    ]


@router.post("")
def create_schedule(data: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    sj = ScheduledJob(name=data.name, workflow_id=data.workflow_id, user_id=user.id, cron=data.cron, input=data.input)
    db.add(sj)
    db.commit()
    db.refresh(sj)
    add_schedule_job(sj)
    return {"id": sj.id, "name": sj.name, "cron": sj.cron, "is_enabled": sj.is_enabled}


@router.post("/{schedule_id}/toggle")
def toggle_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    s = db.get(ScheduledJob, schedule_id)
    if s is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    s.is_enabled = not s.is_enabled
    db.commit()
    if s.is_enabled:
        add_schedule_job(s)
    else:
        remove_schedule_job(s.id)
    return {"id": s.id, "is_enabled": s.is_enabled}


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    s = db.get(ScheduledJob, schedule_id)
    if s is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    remove_schedule_job(s.id)
    db.delete(s)
    db.commit()
    return {"code": 0, "message": "ok"}
