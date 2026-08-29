from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.services import run_service

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def list_runs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return run_service.list_runs(db)


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return run_service.get_run(db, run_id)
