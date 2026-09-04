from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.services import system_service

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
def system_status(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """运行状态与降级项。含依赖可用性，属运维信息，不对 caller 与 API Key 开放。"""
    return system_service.get_system_status(db)
