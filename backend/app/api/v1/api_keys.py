import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import ApiKey, User
from app.db.session import get_db

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class ApiKeyIn(BaseModel):
    name: str
    quota: int = 1000


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@router.get("")
def list_api_keys(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(ApiKey).order_by(ApiKey.id.desc()).all()
    return [
        {"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "quota": k.quota, "used": k.used,
         "is_enabled": k.is_enabled, "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
         "created_at": k.created_at.isoformat() if k.created_at else None}
        for k in rows
    ]


@router.post("")
def create_api_key(data: ApiKeyIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    raw = "ak_" + secrets.token_hex(16)
    ak = ApiKey(
        user_id=user.id,
        name=data.name,
        key_prefix=raw[:12] + "...",
        key_hash=hash_key(raw),
        quota=data.quota,
    )
    db.add(ak)
    db.commit()
    db.refresh(ak)
    return {
        "id": ak.id, "name": ak.name, "key": raw, "key_prefix": ak.key_prefix,
        "quota": ak.quota, "used": ak.used, "is_enabled": ak.is_enabled,
    }


@router.post("/{key_id}/toggle")
def toggle_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    k = db.get(ApiKey, key_id)
    if k is None:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    k.is_enabled = not k.is_enabled
    db.commit()
    return {"id": k.id, "is_enabled": k.is_enabled}


@router.delete("/{key_id}")
def delete_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    k = db.get(ApiKey, key_id)
    if k is None:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    db.delete(k)
    db.commit()
    return {"code": 0, "message": "ok"}
