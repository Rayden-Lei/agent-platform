"""入口限流（FR-025）：按自然分钟的固定窗口计数。

三个维度（API Key / 登录用户 / 匿名 IP）共用同一段逻辑，只是 scope 与上限不同。
选固定窗口而不是滑动窗口：与登录限流是同一套 INCR + EXPIRE 用法，实现与排障成本最低；
窗口边界最多放过 2 倍瞬时流量，对本平台的调用规模可接受。

Redis 不可用时的降级方向按 scope 区分（2026-11-18，配置项 RATE_LIMIT_FAIL_CLOSED_SCOPES）：
- **公开入口 fail-closed**（分享 share / 访客 share_v / 来源 IP ip）：这些入口不要求登录，
  Redis 一挂就等于对外完全无限流，成本闸门（模型费用）与滥用防护同时失效。
  宁可让公开入口暂时 503 不可用，也不能敞开烧钱 —— 公开入口的可用性由分享方自己承担。
- **内部接口 fail-open**（API Key ak / 登录用户 user）：调用方已经通过鉴权，
  是平台自己的使用者。因为限流组件故障把整站调用全拒掉，等于用一个保护措施制造一次更大的故障，
  且这类调用方本来就有审计与配额（API Key 还有数据库层的 used/quota 硬上限）兜底。
降级一律在 status() 与 /system/status 里可见（docs/06 第 13.3 节的三件事）。
"""
import logging
import time
from dataclasses import dataclass

import redis

from app.config import settings
from app.core import redis_client
from app.core.exceptions import BizError

logger = logging.getLogger(__name__)

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


def fail_closed_scopes() -> frozenset[str]:
    """Redis 故障时应当拒绝（而不是放行）的 scope 名单。

    每次调用都重新解析配置，不做模块级缓存：测试要能 monkeypatch 配置立即生效，
    而这条路径本身只在 Redis 故障时才走到，解析一个短字符串的成本可以忽略。
    """
    return frozenset(s.strip() for s in (settings.RATE_LIMIT_FAIL_CLOSED_SCOPES or "").split(",") if s.strip())


def _degraded_result(scope: str, limit: int, retry_after: int) -> RateLimitResult:
    """Redis 故障时的降级结果：按 scope 决定拒绝还是放行，并在日志里写清降级方向。"""
    if scope in fail_closed_scopes():
        # 公开入口：拒绝。文案不说"Redis 故障"（外部调用方看这个没用，也不该知道内部组件），
        # 但要带 Retry-After 让守规矩的调用方退避重试。
        logger.warning("Redis 不可用，scope=%s 属公开入口（fail-closed），本次请求被拒绝", scope)
        return RateLimitResult(False, limit, 0, retry_after)
    logger.warning("Redis 不可用，scope=%s 属内部接口（fail-open），本次请求放行且未计数", scope)
    return RateLimitResult(True, limit, limit, 0)


def check(scope: str, key: str, limit: int) -> RateLimitResult:
    """计一次并判定是否超限。

    scope 形如 ak / user / ip，key 为该维度的标识；limit <= 0 或总开关关闭时不限流。
    先 INCR 再判定：超限的请求也计数，避免"恰好卡在上限的调用方"反复探测。
    """
    if not settings.RATE_LIMIT_ENABLED or limit <= 0:
        return RateLimitResult(True, limit, limit, 0)
    bucket, retry_after = _window(_clock())
    client = redis_client.get_redis()
    if client is None:
        # 客户端初始化就失败了（REDIS_URL 非法等）：与"调用时连不上"同一套降级判定，
        # 2026-11-18 前这里无条件放行，公开入口在 Redis 缺失时完全裸奔
        return _degraded_result(scope, limit, retry_after)

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
        return _degraded_result(scope, limit, retry_after)

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
    """限流状态。enabled=False 表示当前没有完整的速率保护：configured=False 是配置关闭，否则是 Redis 故障。

    Redis 故障时（2026-11-18 起）还要报**降级方向**，因为两侧语义不同：
    public_fail_closed=True 表示公开入口已被拒绝（不是"没保护"，而是"主动拒绝"，可用性受损）；
    内部接口照常放行但未计数（保护缺失）。只报 enabled=False 会让人误以为全部裸奔，
    只报"已降级"又看不出公开入口其实是安全的。两者分开报，运维才知道要不要紧急修 Redis。
    """
    base = {
        "api_key_per_minute": settings.RATE_LIMIT_API_KEY_PER_MINUTE,
        "user_per_minute": settings.RATE_LIMIT_USER_PER_MINUTE,
        "ip_per_minute": settings.RATE_LIMIT_IP_PER_MINUTE,
        "fail_closed_scopes": sorted(fail_closed_scopes()),
    }
    if not settings.RATE_LIMIT_ENABLED:
        return {**base, "enabled": False, "configured": False, "degraded": False,
                "public_fail_closed": False, "reason": "配置关闭（RATE_LIMIT_ENABLED=false）"}
    redis_state = redis_client.redis_status()
    if not redis_state["available"]:
        # 公开入口（share / share_v / ip）在名单里时它们是被拒绝的，不是被放行的
        public_closed = bool({"share", "share_v", "ip"} & fail_closed_scopes())
        return {**base, "enabled": False, "configured": True, "degraded": True, "public_fail_closed": public_closed,
                "reason": redis_state["reason"]}
    return {**base, "enabled": True, "configured": True, "degraded": False, "public_fail_closed": False, "reason": None}
