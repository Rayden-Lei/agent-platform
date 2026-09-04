import logging

import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.security import create_access_token, verify_password
from app.db.models import User
from app.schemas import TokenOut, UserOut

logger = logging.getLogger(__name__)

MAX_LOGIN_FAIL = 5
LOCK_SECONDS = 600  # 10 分钟

# Redis 不可用时登录限流会静默失效（暴力破解无保护），因此每次故障都记 WARN，
# 并把最近一次故障原因留在 _redis_error 里，由 login_guard_status() 暴露给系统状态接口。
_redis = None
_redis_error: str | None = None
try:
    _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
except (redis.RedisError, ValueError) as e:
    _redis_error = f"Redis 客户端初始化失败：{e}"
    logger.warning("%s，登录限流已关闭", _redis_error)


def _fail_key(username: str) -> str:
    """某用户名对应的失败计数 Redis key。"""
    return f"login_fail:{username}"


def _mark_down(operation: str, exc: Exception) -> None:
    """记录一次 Redis 故障（限流本次未生效），供系统状态接口暴露。"""
    global _redis_error
    _redis_error = f"{operation}失败：{exc}"
    logger.warning("Redis %s，登录限流本次未生效", _redis_error)


def _mark_up() -> None:
    """Redis 恢复后清除故障记录，并打一条恢复日志。"""
    global _redis_error
    if _redis_error is not None:
        logger.info("Redis 已恢复，登录限流重新生效")
    _redis_error = None


def _fail_count(username: str) -> int:
    """读取某用户名的连续失败次数；Redis 不可用时返回 0（放行本次登录，可用性优先）。"""
    if _redis is None:
        return 0
    try:
        v = _redis.get(_fail_key(username))
        _mark_up()
        return int(v) if v else 0
    except (redis.RedisError, ValueError) as e:
        # 读不到计数就放行本次登录（可用性优先），但状态要被记录下来
        _mark_down("读取登录失败次数", e)
        return 0


def _incr_fail(username: str) -> None:
    """失败次数 +1 并重置锁定窗口（10 分钟过期）；Redis 不可用时静默跳过。"""
    if _redis is None:
        return
    try:
        key = _fail_key(username)
        _redis.incr(key)
        _redis.expire(key, LOCK_SECONDS)
        _mark_up()
    except redis.RedisError as e:
        _mark_down("累加登录失败次数", e)


def _clear_fail(username: str) -> None:
    """登录成功后清除失败计数，避免历史失败累积导致误锁。"""
    if _redis is None:
        return
    try:
        _redis.delete(_fail_key(username))
        _mark_up()
    except redis.RedisError as e:
        _mark_down("清除登录失败次数", e)


def login_guard_status() -> dict:
    """登录限流状态。enabled=False 表示当前没有暴力破解保护，需要有人处理。"""
    base = {"max_fail": MAX_LOGIN_FAIL, "lock_seconds": LOCK_SECONDS}
    if _redis is None:
        return {**base, "enabled": False, "reason": _redis_error or "Redis 未配置"}
    try:
        _redis.ping()
    except redis.RedisError as e:
        return {**base, "enabled": False, "reason": f"Redis 不可用：{e}"}
    return {**base, "enabled": True, "reason": None}


def login(db: Session, username: str, password: str) -> TokenOut:
    """登录：限流 → 校验凭据 → 校验可用 → 发 token 并写审计。"""
    if _fail_count(username) >= MAX_LOGIN_FAIL:
        raise BizError(429, "登录失败次数过多，请10分钟后再试")

    user = db.query(User).filter(User.username == username).first()
    if user is None or not verify_password(password, user.password_hash):
        _incr_fail(username)
        record_audit(db, None, "login_failed", "auth", detail={"username": username})
        raise BizError(401, "用户名或密码错误")
    if not user.is_active:
        raise BizError(403, "账号已停用")

    _clear_fail(username)
    record_audit(db, user, "login", "auth")
    token = create_access_token(user.id, user.role)
    return TokenOut(token=token, user=UserOut.model_validate(user))
