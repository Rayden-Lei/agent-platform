import hashlib
import secrets

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.db.models import ApiKey, User


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def list_api_keys(db: Session) -> list[dict]:
    rows = db.query(ApiKey).order_by(ApiKey.id.desc()).all()
    return [
        {"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "quota": k.quota, "used": k.used,
         "is_enabled": k.is_enabled, "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
         "created_at": k.created_at.isoformat() if k.created_at else None}
        for k in rows
    ]


def create_api_key(db: Session, data, user: User) -> dict:
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


def toggle_api_key(db: Session, key_id: int) -> dict:
    k = db.get(ApiKey, key_id)
    if k is None:
        raise BizError(404, "API Key 不存在")
    k.is_enabled = not k.is_enabled
    db.commit()
    return {"id": k.id, "is_enabled": k.is_enabled}


def delete_api_key(db: Session, key_id: int) -> None:
    k = db.get(ApiKey, key_id)
    if k is None:
        raise BizError(404, "API Key 不存在")
    db.delete(k)
    db.commit()
