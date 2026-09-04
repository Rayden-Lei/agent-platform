import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import ApiKey, User


def hash_key(key: str) -> str:
    """对明文 Key 做 SHA-256 单向哈希：库中只存哈希，明文无法还原。"""
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


def list_api_keys(db: Session, params: PageParams) -> dict:
    """分页列出当前用户的 Key 元信息（只含前缀，永不返回明文）。"""
    return paginate(db.query(ApiKey).order_by(ApiKey.id.desc()), params, lambda k: {
        "id": k.id, "name": k.name, "key_prefix": k.key_prefix, "quota": k.quota, "used": k.used,
        "is_enabled": k.is_enabled, "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    })


def create_api_key(db: Session, data, user: User) -> dict:
    """生成新 Key：明文只在此次响应返回一次，之后无法找回（落库仅存哈希与前缀）。"""
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
    """启用/停用某个 Key（停用后 authenticate 会直接拒绝）。"""
    k = db.get(ApiKey, key_id)
    if k is None:
        raise BizError(404, "API Key 不存在")
    k.is_enabled = not k.is_enabled
    db.commit()
    return {"id": k.id, "is_enabled": k.is_enabled}


def delete_api_key(db: Session, key_id: int) -> None:
    """删除 Key（立即失效），不存在抛 BizError(404)。"""
    k = db.get(ApiKey, key_id)
    if k is None:
        raise BizError(404, "API Key 不存在")
    db.delete(k)
    db.commit()
