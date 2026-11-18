"""入口限流的降级方向（2026-11-18）：Redis 故障时公开入口 fail-closed、内部接口 fail-open。

2026-11-18 前 `rate_limiter.check` 在 Redis 不可用时一律 return allowed=True，
公开入口（分享 / 访客 / 来源 IP）完全裸奔 —— 成本闸门与滥用防护同时失效且无人知晓。
现在降级方向由 RATE_LIMIT_FAIL_CLOSED_SCOPES 配置，两侧默认不同（理由见 rate_limiter 模块 docstring），
降级必须在 status() 与 /system/status 里看得见。
"""
import pytest

from app.config import settings
from app.core import rate_limiter, redis_client


class _DeadRedis:
    """连不上 / 命令报错的 Redis：所有命令都抛 RedisError，模拟真实故障。"""

    def pipeline(self):
        raise redis_error()


def redis_error():
    import redis
    return redis.RedisError("模拟 Redis 不可用")


def _break_redis(monkeypatch):
    """让 get_redis() 返回一个所有命令都失败的客户端（"连上了但命令失败"这条分支）。"""
    monkeypatch.setattr(redis_client, "get_redis", lambda: _DeadRedis())


def _no_redis(monkeypatch):
    """让 get_redis() 返回 None（客户端初始化就失败，REDIS_URL 非法等）。"""
    monkeypatch.setattr(redis_client, "get_redis", lambda: None)


@pytest.fixture(autouse=True)
def _enable_and_freeze(monkeypatch):
    """打开限流并固定时钟，避免跨窗口边界的偶发失败。"""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED_SCOPES", "share,share_v,ip")
    monkeypatch.setattr(rate_limiter, "_clock", lambda: 1_800_000_000.0)


@pytest.mark.parametrize("scope", ["share", "share_v", "ip"])
def test_public_scopes_are_rejected_when_redis_fails(scope, monkeypatch):
    """公开入口在 Redis 故障时必须被拒绝 —— 这是本次修复的核心断言。"""
    _break_redis(monkeypatch)
    result = rate_limiter.check(scope, "k", 10)
    assert result.allowed is False, f"{scope} 是公开入口，Redis 故障时应 fail-closed"
    assert result.remaining == 0
    assert result.retry_after >= 1


@pytest.mark.parametrize("scope", ["ak", "user"])
def test_internal_scopes_stay_open_when_redis_fails(scope, monkeypatch):
    """内部接口（已鉴权的调用方）在 Redis 故障时继续放行：不能因为限流组件故障把整站拒掉。"""
    _break_redis(monkeypatch)
    result = rate_limiter.check(scope, "k", 10)
    assert result.allowed is True, f"{scope} 是内部接口，Redis 故障时应 fail-open"


@pytest.mark.parametrize("scope", ["share", "share_v", "ip"])
def test_public_scopes_rejected_when_redis_client_missing(scope, monkeypatch):
    """客户端初始化失败（get_redis() 返回 None）走同一套降级判定，不能无条件放行。"""
    _no_redis(monkeypatch)
    assert rate_limiter.check(scope, "k", 10).allowed is False


@pytest.mark.parametrize("scope", ["ak", "user"])
def test_internal_scopes_open_when_redis_client_missing(scope, monkeypatch):
    _no_redis(monkeypatch)
    assert rate_limiter.check(scope, "k", 10).allowed is True


def test_degradation_direction_is_configurable(monkeypatch):
    """改成 fail-open 名单后行为要跟着变：这是"可配置"，不是写死。"""
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED_SCOPES", "ak")
    _no_redis(monkeypatch)
    assert rate_limiter.check("ak", "k", 10).allowed is False
    assert rate_limiter.check("share", "k", 10).allowed is True


def test_empty_fail_closed_list_means_all_fail_open(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED_SCOPES", "")
    _no_redis(monkeypatch)
    for scope in ("share", "share_v", "ip", "ak", "user"):
        assert rate_limiter.check(scope, "k", 10).allowed is True


def test_limit_exceeded_turns_into_429(monkeypatch):
    """fail-closed 的结果经 limit_exceeded 变成 429 + Retry-After，调用方据此退避。"""
    _no_redis(monkeypatch)
    result = rate_limiter.check("share", "k", 10)
    err = rate_limiter.limit_exceeded(result)
    assert err.status_code == 429
    assert "请求过于频繁" in err.detail
    assert err.headers["Retry-After"] == str(result.retry_after)


def test_status_reports_fail_closed_when_redis_down(client, auth_headers, monkeypatch):
    """/system/status 要能看出"公开入口被拒绝"与"全部放行"的区别。"""
    monkeypatch.setattr(redis_client, "redis_status", lambda: {"available": False, "reason": "模拟 Redis 不可用"})
    body = client.get("/api/v1/system/status", headers=auth_headers).json()
    rl = body["rate_limit"]
    assert rl["enabled"] is False
    assert rl["degraded"] is True
    assert rl["public_fail_closed"] is True
    assert rl["fail_closed_scopes"] == ["ip", "share", "share_v"]
    message = next(d["message"] for d in body["degraded"] if d["item"] == "rate_limit")
    # 文案必须说清"公开入口已改为拒绝"，不能含糊成"没保护"
    assert "公开入口" in message and "拒绝" in message


def test_status_reports_fail_open_when_list_is_empty(client, auth_headers, monkeypatch):
    """名单为空（全部放行）时状态里不能声称公开入口已被拒绝。"""
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED_SCOPES", "")
    monkeypatch.setattr(redis_client, "redis_status", lambda: {"available": False, "reason": "模拟 Redis 不可用"})
    rl = client.get("/api/v1/system/status", headers=auth_headers).json()["rate_limit"]
    assert rl["public_fail_closed"] is False
    assert rl["degraded"] is True


def test_status_healthy_has_no_degradation(client, auth_headers, monkeypatch):
    monkeypatch.setattr(redis_client, "redis_status", lambda: {"available": True, "reason": None})
    rl = client.get("/api/v1/system/status", headers=auth_headers).json()["rate_limit"]
    assert (rl["enabled"], rl["degraded"], rl["public_fail_closed"]) == (True, False, False)


def test_public_share_chat_is_rejected_when_redis_down(client, auth_headers, monkeypatch):
    """端到端：Redis 故障时公开分享的对话入口返回 429，而不是照常放行。

    直接调服务层（不经 HTTP）是为了不依赖分享夹具：这里验的是"公开入口被拒"这一条链路。
    """
    from app.services import share_service

    class _Guest:
        share = type("S", (), {"id": 1, "rate_limit_per_minute": 20, "daily_message_limit": 1000, "visitor_daily_limit": 50})()
        visitor_id = "v_pytest"

    _no_redis(monkeypatch)
    with pytest.raises(Exception) as exc:
        share_service.check_chat_quota(None, _Guest())
    assert getattr(exc.value, "status_code", None) == 429
    assert "请求过于频繁" in exc.value.detail
