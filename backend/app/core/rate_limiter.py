"""入口限流（FR-025）：按自然分钟的固定窗口计数。

三个维度（API Key / 登录用户 / 匿名 IP）共用同一段逻辑，只是 scope 与上限不同。
选固定窗口而不是滑动窗口：与登录限流是同一套 INCR + EXPIRE 用法，实现与排障成本最低；
窗口边界最多放过 2 倍瞬时流量，对本平台的调用规模可接受。
Redis 不可用时放行并记录故障（core/redis_client），系统状态接口据此报降级。
"""
import time
from dataclasses import dataclass

import redis

from app.config import settings
from app.core import redis_client
from app.core.exceptions import BizError

WINDOW_SECONDS = 60
HEADER_LIMIT = "X-RateLimit-Limit"
HEADER_REMAINING = "X-RateLimit-Remaining"
HEADER_RETRY_AFTER = "Retry-After"

# 可注入的时钟：测试用固定时间避免跨窗口边界的偶发失败
_clock = time.time


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # 到下一窗口的秒数；allowed=True 时为 0


def _window(now: float) -> tuple[int, int]:
    """当前窗口编号与距窗口结束的秒数（至少 1 秒，Retry-After 为 0 会让调用方立刻重试）。"""
    bucket = int(now // WINDOW_SECONDS)
    retry_after = WINDOW_SECONDS - int(now % WINDOW_SECONDS)
    return bucket, max(retry_after, 1)


def check(scope: str, key: str, limit: int) -> RateLimitResult:
    """计一次并判定是否超限。

    scope 形如 ak / user / ip，key 为该维度的标识；limit <= 0 或总开关关闭时不限流。
    先 INCR 再判定：超限的请求也计数，避免"恰好卡在上限的调用方"反复探测。
    """
    if not settings.RATE_LIMIT_ENABLED or limit <= 0:
        return RateLimitResult(True, limit, limit, 0)
    client = redis_client.get_redis()
    if client is None:
        return RateLimitResult(True, limit, limit, 0)

    bucket, retry_after = _window(_clock())
    redis_key = f"rl:{scope}:{key}:{bucket}"
    try:
        pipe = client.pipeline()
        pipe.incr(redis_key)
        # 过期略长于窗口：窗口结束后 key 自然消失，不需要清理任务
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        count, _ = pipe.execute()
        redis_client.mark_up()
    except redis.RedisError as e:
        redis_client.mark_down(f"{scope} 限流计数", e)
        return RateLimitResult(True, limit, limit, 0)

    count = int(count)
    if count > limit:
        return RateLimitResult(False, limit, 0, retry_after)
    return RateLimitResult(True, limit, limit - count, 0)


def limit_exceeded(result: RateLimitResult) -> BizError:
    """把超限结果变成统一的 429：可展示的提示 + Retry-After + X-RateLimit-*（Remaining 恒为 0）。

    三个维度共用，调用方 `raise limit_exceeded(result)` 即可，不必各自拼文案与响应头。
    """
    return BizError(
        429,
        f"请求过于频繁，请 {result.retry_after} 秒后重试",
        headers={
            HEADER_RETRY_AFTER: str(result.retry_after),
            HEADER_LIMIT: str(result.limit),
            HEADER_REMAINING: "0",
        },
    )


def status() -> dict:
    """限流状态。enabled=False 表示当前没有速率保护：configured=False 是配置关闭，否则是 Redis 故障。"""
    base = {
        "api_key_per_minute": settings.RATE_LIMIT_API_KEY_PER_MINUTE,
        "user_per_minute": settings.RATE_LIMIT_USER_PER_MINUTE,
        "ip_per_minute": settings.RATE_LIMIT_IP_PER_MINUTE,
    }
    if not settings.RATE_LIMIT_ENABLED:
        return {**base, "enabled": False, "configured": False, "reason": "配置关闭（RATE_LIMIT_ENABLED=false）"}
    redis_state = redis_client.redis_status()
    if not redis_state["available"]:
        return {**base, "enabled": False, "configured": True, "reason": redis_state["reason"]}
    return {**base, "enabled": True, "configured": True, "reason": None}
