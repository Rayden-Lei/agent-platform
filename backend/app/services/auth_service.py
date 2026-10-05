import logging
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core import redis_client
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import AuditLog, User
from app.schemas import MeOut, ProfileUpdateIn, TokenOut, UserOut

logger = logging.getLogger(__name__)

MAX_LOGIN_FAIL = 5
LOCK_SECONDS = 600  # 10 分钟

# Redis 不可用时登录限流会静默失效（暴力破解无保护）：客户端与故障记录由 core/redis_client 统一维护，
# 每次故障都记 WARN，并由 login_guard_status() 暴露给系统状态接口。


def _fail_key(username: str) -> str:
    """某用户名登录失败计数的 Redis key。"""
    return f"login_fail:{username}"


def _pw_fail_key(user_id: int) -> str:
    """本人改密时"当前密码"输错的计数 key：拿到会话的人也不能借改密接口暴力试原密码（docs/15 OP-04）。"""
    return f"pwchange_fail:{user_id}"


def _fail_count(key: str) -> int:
    """读取连续失败次数；Redis 不可用时返回 0（放行本次请求，可用性优先）。"""
    client = redis_client.get_redis()
    if client is None:
        return 0
    try:
        v = client.get(key)
        redis_client.mark_up()
        return int(v) if v else 0
    except (redis.RedisError, ValueError) as e:
        # 读不到计数就放行本次请求（可用性优先），但状态要被记录下来
        redis_client.mark_down("读取登录失败次数", e)
        return 0


def _incr_fail(key: str) -> None:
    """失败次数 +1 并重置锁定窗口（10 分钟过期）；Redis 不可用时静默跳过。"""
    client = redis_client.get_redis()
    if client is None:
        return
    try:
        client.incr(key)
        client.expire(key, LOCK_SECONDS)
        redis_client.mark_up()
    except redis.RedisError as e:
        redis_client.mark_down("累加登录失败次数", e)


def _clear_fail(key: str) -> None:
    """成功后清除失败计数，避免历史失败累积导致误锁。"""
    client = redis_client.get_redis()
    if client is None:
        return
    try:
        client.delete(key)
        redis_client.mark_up()
    except redis.RedisError as e:
        redis_client.mark_down("清除登录失败次数", e)


def login_guard_status() -> dict:
    """登录限流状态。enabled=False 表示当前没有暴力破解保护，需要有人处理。"""
    base = {"max_fail": MAX_LOGIN_FAIL, "lock_seconds": LOCK_SECONDS}
    status = redis_client.redis_status()
    if not status["available"]:
        return {**base, "enabled": False, "reason": status["reason"]}
    return {**base, "enabled": True, "reason": None}


def login(db: Session, username: str, password: str) -> TokenOut:
    """登录：限流 → 校验凭据 → 校验可用 → 发 token 并写审计。"""
    if _fail_count(_fail_key(username)) >= MAX_LOGIN_FAIL:
        raise BizError(429, "登录失败次数过多，请10分钟后再试")

    user = db.query(User).filter(User.username == username).first()
    if user is None or not verify_password(password, user.password_hash):
        _incr_fail(_fail_key(username))
        record_audit(db, None, "login_failed", "auth", detail={"username": username})
        raise BizError(401, "用户名或密码错误")
    if not user.is_active:
        raise BizError(403, "账号已停用")

    _clear_fail(_fail_key(username))
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    record_audit(db, user, "login", "auth")
    # 必须改密的账号照样能登录：拿到令牌后只能调改密与 /auth/me（core/deps），前端据 user.must_change_password 弹改密框
    token = create_access_token(user.id, user.role, user.token_version)
    return TokenOut(token=token, user=UserOut.model_validate(user))


LOGIN_HISTORY_LIMIT = 20
LOGIN_HISTORY_DAYS = 90  # 登录记录只看近 90 天：audit_logs 没有按动作的索引，靠 created_at 索引把扫描范围框住


def mask_phone(phone: str | None) -> str | None:
    """手机号脱敏：只露前 3 后 4 位（不足 8 位时全遮），接口与页面都只出现脱敏值（安全规范：不出现完整手机号）。"""
    if not phone:
        return None
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 8 else "****"


def profile_of(user: User) -> MeOut:
    """GET /auth/me 的响应：账号信息 + 对外地址 + 个人资料（手机号脱敏）。"""
    return MeOut(**UserOut.model_validate(user).model_dump(), public_base_url=settings.PUBLIC_BASE_URL,
                 display_name=user.display_name, email=user.email, phone_masked=mask_phone(user.phone),
                 password_changed_at=user.password_changed_at, last_login_at=user.last_login_at)


def update_profile(db: Session, user: User, data: ProfileUpdateIn) -> MeOut:
    """本人改资料（docs/15 OP-03）：只改请求里带了的字段（null 清除），什么都没变不写库。
    审计 update / user，detail 只记改了哪些字段——邮箱与手机号是个人信息，不进审计。"""
    changed = [f for f in data.model_fields_set if getattr(user, f) != getattr(data, f)]
    if changed:
        for f in changed:
            setattr(user, f, getattr(data, f))
        db.commit()
        db.refresh(user)
        record_audit(db, user, "update", "user", user.id, detail={"username": user.username, "changed": sorted(changed), "self": True})
    return profile_of(user)


def logout_others(db: Session, user: User) -> TokenOut:
    """退出其他设备（docs/15 OP-03）：token_version +1，本人此前签发的令牌全部失效；返回新令牌，当前页面换上后继续用。
    审计 logout_others。"""
    user.token_version += 1
    db.commit()
    db.refresh(user)
    record_audit(db, user, "logout_others", "user", user.id, detail={"username": user.username})
    return TokenOut(token=create_access_token(user.id, user.role, user.token_version), user=UserOut.model_validate(user))


def login_history(db: Session, user: User) -> list[dict]:
    """本人最近的登录记录（近 90 天、最多 20 条，新的在前）：成功的按 user_id 认，失败的按审计里记的用户名认
    （失败时还不知道是谁，login_failed 只记了用户名）。只给时间、来源 IP 与成败。"""
    since = datetime.now(timezone.utc) - timedelta(days=LOGIN_HISTORY_DAYS)
    rows = (db.query(AuditLog.created_at, AuditLog.ip, AuditLog.action)
            .filter(AuditLog.created_at >= since, AuditLog.action.in_(("login", "login_failed")),
                    or_(AuditLog.user_id == user.id, and_(AuditLog.user_id.is_(None), AuditLog.detail["username"].astext == user.username)))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(LOGIN_HISTORY_LIMIT).all())
    return [{"created_at": r.created_at.isoformat(), "ip": r.ip, "success": r.action == "login"} for r in rows]


def change_password(db: Session, user: User, old_password: str, new_password: str) -> TokenOut:
    """本人改密（docs/15 OP-04）：当前密码错 400（连错 5 次锁 10 分钟）、新旧相同 400；长度由 ChangePasswordIn 管（422）。
    成功后 token_version +1（本人在其他设备上的会话与旧令牌全部失效）、清掉必须改密标记，返回新令牌供当前页面继续用。
    写审计 change_password，不记密码。"""
    key = _pw_fail_key(user.id)
    if _fail_count(key) >= MAX_LOGIN_FAIL:
        raise BizError(429, "当前密码输错次数过多，请10分钟后再试")
    if not verify_password(old_password, user.password_hash):
        _incr_fail(key)
        raise BizError(400, "当前密码不正确")
    if old_password == new_password:
        raise BizError(400, "新密码不能与当前密码相同")
    _clear_fail(key)
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    record_audit(db, user, "change_password", "user", user.id, detail={"username": user.username})
    return TokenOut(token=create_access_token(user.id, user.role, user.token_version), user=UserOut.model_validate(user))
