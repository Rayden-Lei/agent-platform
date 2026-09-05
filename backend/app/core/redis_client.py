"""进程内共享的 Redis 客户端与故障记录。

登录限流与入口限流（FR-025）都依赖 Redis，且都采用同一种策略：Redis 不可用则放行，但降级必须可见。
客户端与最近一次故障原因放在一处，系统状态接口只问一次，两处限流也不会各自维护一份不一致的故障记录。
"""
import logging

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None
# 最近一次故障原因；None 表示当前正常。故障时打 WARN，恢复时打 INFO，两者都不能静默
_last_error: str | None = None

try:
    _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
except (redis.RedisError, ValueError) as e:
    _last_error = f"Redis 客户端初始化失败：{e}"
    logger.warning("%s，依赖 Redis 的限流全部关闭", _last_error)


def get_redis() -> redis.Redis | None:
    """共享客户端；初始化失败时为 None，调用方按"放行"处理并保持降级可见。"""
    return _client


def mark_down(operation: str, exc: Exception) -> None:
    """记录一次 Redis 故障（本次限流未生效），供系统状态接口暴露。"""
    global _last_error
    _last_error = f"{operation}失败：{exc}"
    logger.warning("Redis %s，依赖 Redis 的限流本次放行", _last_error)


def mark_up() -> None:
    """Redis 调用成功后清除故障记录；从故障中恢复时打一条 INFO，便于对照时间线。"""
    global _last_error
    if _last_error is not None:
        logger.info("Redis 已恢复，限流重新生效")
    _last_error = None


def redis_status() -> dict:
    """{available, reason}：available=False 表示依赖 Redis 的保护当前没有生效，需要有人处理。"""
    if _client is None:
        return {"available": False, "reason": _last_error or "Redis 未配置"}
    try:
        _client.ping()
    except redis.RedisError as e:
        return {"available": False, "reason": f"Redis 不可用：{e}"}
    return {"available": True, "reason": None}
