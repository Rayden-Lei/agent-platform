from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.services import api_key_service

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class ApiKeyIn(BaseModel):
    name: str
    quota: int = 1000


@router.get("")
def list_api_keys(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return api_key_service.list_api_keys(db)


@router.post("")
def create_api_key(data: ApiKeyIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return api_key_service.create_api_key(db, data, user)


@router.post("/{key_id}/toggle")
def toggle_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return api_key_service.toggle_api_key(db, key_id)


@router.delete("/{key_id}")
def delete_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    api_key_service.delete_api_key(db, key_id)
    return {"code": 0, "message": "ok"}
