import hashlib
import ipaddress
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core import rate_limiter
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.core.rate_limiter import RateLimitResult
from app.core.request_context import get_client_ip
from app.db.models import ApiKey, User


def hash_key(key: str) -> str:
    """对明文 Key 做 SHA-256 单向哈希：库中只存哈希，明文无法还原。"""
    return hashlib.sha256(key.encode()).hexdigest()


def _ip_allowed(ip: str | None, allowed_ips: list) -> bool:
    """来源是否在白名单内。白名单为空不限制；有白名单但来源缺失或不是合法 IP 时按不允许（判不出来源宁可拒绝）。"""
    if not allowed_ips:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(item, strict=False) for item in allowed_ips)


def authenticate(db: Session, raw_key: str) -> tuple[User, ApiKey, RateLimitResult]:
    """用明文 Key 鉴权并扣减一次配额，返回 (归属用户, Key, 限流结果)。

    判定顺序：Key 有效 → 归属账号可用 → 来源 IP 白名单 → 限流 → 扣配额。
    白名单与限流放在扣配额之前：被拒绝、被限流的请求不消耗配额。
    扣配额用带前置条件的 UPDATE（used < quota）并按影响行数判断，并发请求下不会超扣。
    """
    ak = db.query(ApiKey).filter(ApiKey.key_hash == hash_key(raw_key)).first()
    if ak is None or not ak.is_enabled:
        raise BizError(401, "API Key 无效或已停用")
    user = db.get(User, ak.user_id)
    if user is None or not user.is_active:
        raise BizError(403, "API Key 归属账号不可用")

    client_ip = get_client_ip()
    if not _ip_allowed(client_ip, ak.allowed_ips or []):
        # 记到 Key 归属账号名下：审计要能按 Key 追溯"谁的 Key 被什么来源拿去调了"
        record_audit(db, user, "api_key_ip_rejected", "api_key", ak.id, detail={"ip": client_ip, "key_prefix": ak.key_prefix})
        raise BizError(403, "API Key 不允许从该 IP 调用")

    limit = ak.rate_limit_per_minute or settings.RATE_LIMIT_API_KEY_PER_MINUTE
    rate_limit = rate_limiter.check("ak", str(ak.id), limit)
    if not rate_limit.allowed:
        raise rate_limiter.limit_exceeded(rate_limit)

    consumed = (
        db.query(ApiKey)
        .filter(ApiKey.id == ak.id, ApiKey.used < ApiKey.quota)
        .update({ApiKey.used: ApiKey.used + 1, ApiKey.last_used_at: datetime.now(timezone.utc)}, synchronize_session=False)
    )
    db.commit()
    if not consumed:
        raise BizError(429, "API Key 配额已用尽")
    db.refresh(ak)
    return user, ak, rate_limit


def _to_dict(k: ApiKey) -> dict:
    """Key 元信息（只含前缀，永不返回明文与哈希）。"""
    return {
        "id": k.id, "name": k.name, "key_prefix": k.key_prefix, "quota": k.quota, "used": k.used,
        "is_enabled": k.is_enabled, "allowed_ips": k.allowed_ips or [], "rate_limit_per_minute": k.rate_limit_per_minute,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


def _get_owned(db: Session, key_id: int, user: User) -> ApiKey:
    """按 id 取 Key。developer 只能取到本人创建的，他人的一律 404（不暴露存在性）；admin 不受限。"""
    k = db.get(ApiKey, key_id)
    if k is None or (user.role != "admin" and k.user_id != user.id):
        raise BizError(404, "API Key 不存在")
    return k


def list_api_keys(db: Session, params: PageParams, user: User) -> dict:
    """分页列出 Key 元信息：admin 看全部，developer 只看本人创建的。"""
    query = db.query(ApiKey)
    if user.role != "admin":
        query = query.filter(ApiKey.user_id == user.id)
    return paginate(query.order_by(ApiKey.id.desc()), params, _to_dict)


def create_api_key(db: Session, data, user: User) -> dict:
    """生成新 Key：明文只在此次响应返回一次，之后无法找回（落库仅存哈希与前缀）。"""
    raw = "ak_" + secrets.token_hex(16)
    ak = ApiKey(
        user_id=user.id,
        name=data.name,
        key_prefix=raw[:12] + "...",
        key_hash=hash_key(raw),
        quota=data.quota,
        allowed_ips=data.allowed_ips,
        rate_limit_per_minute=data.rate_limit_per_minute,
    )
    db.add(ak)
    db.commit()
    db.refresh(ak)
    return {**_to_dict(ak), "key": raw}


def update_api_key(db: Session, key_id: int, data, user: User) -> dict:
    """只更新请求里传了的字段（None 表示未提供）；归属校验见 _get_owned。"""
    k = _get_owned(db, key_id, user)
    for field in ("name", "quota", "allowed_ips", "rate_limit_per_minute"):
        value = getattr(data, field)
        if value is not None:
            setattr(k, field, value)
    db.commit()
    db.refresh(k)
    return _to_dict(k)


def toggle_api_key(db: Session, key_id: int, user: User) -> dict:
    """启用/停用某个 Key（停用后 authenticate 会直接拒绝）。"""
    k = _get_owned(db, key_id, user)
    k.is_enabled = not k.is_enabled
    db.commit()
    return {"id": k.id, "is_enabled": k.is_enabled}


def delete_api_key(db: Session, key_id: int, user: User) -> None:
    """删除 Key（立即失效），不存在或不属于本人抛 BizError(404)。"""
    k = _get_owned(db, key_id, user)
    db.delete(k)
    db.commit()
