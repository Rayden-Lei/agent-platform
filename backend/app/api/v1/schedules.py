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
    name: str
    workflow_id: int
    cron: str
    input: dict = {}


@router.get("")
def list_schedules(params: PageParams = Depends(page_params), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return schedule_service.list_schedules(db, params)


@router.post("")
def create_schedule(data: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return schedule_service.create_schedule(db, data, user)


@router.post("/{schedule_id}/toggle")
def toggle_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return schedule_service.toggle_schedule(db, schedule_id)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    schedule_service.delete_schedule(db, schedule_id)
    return {"code": 0, "message": "ok"}
