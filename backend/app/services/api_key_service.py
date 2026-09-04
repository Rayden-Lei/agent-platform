import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.db.models import ApiKey, User


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def authenticate(db: Session, raw_key: str) -> tuple[User, ApiKey]:
    """用明文 Key 鉴权并扣减一次配额，返回 (归属用户, Key)。

    先校验 Key 与归属账号，再扣配额，避免账号不可用时白白消耗配额。
    扣配额用带前置条件的 UPDATE（used < quota）并按影响行数判断，并发请求下不会超扣。
    """
    ak = db.query(ApiKey).filter(ApiKey.key_hash == hash_key(raw_key)).first()
    if ak is None or not ak.is_enabled:
        raise BizError(401, "API Key 无效或已停用")
    user = db.get(User, ak.user_id)
    if user is None or not user.is_active:
        raise BizError(403, "API Key 归属账号不可用")

    consumed = (
        db.query(ApiKey)
        .filter(ApiKey.id == ak.id, ApiKey.used < ApiKey.quota)
        .update({ApiKey.used: ApiKey.used + 1, ApiKey.last_used_at: datetime.now(timezone.utc)}, synchronize_session=False)
    )
    db.commit()
    if not consumed:
        raise BizError(429, "API Key 配额已用尽")
    db.refresh(ak)
    return user, ak


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
