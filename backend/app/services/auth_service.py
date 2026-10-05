import logging
from datetime import datetime, timezone

import redis
from sqlalchemy.orm import Session

from app.core import redis_client
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas import TokenOut, UserOut

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
