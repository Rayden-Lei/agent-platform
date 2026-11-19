"""Redis 客户端与故障记录（core/redis_client.py）。

为什么单独测：这个模块的每条分支都决定"限流到底有没有生效"。
- Redis 连不上时必须**放行**（不能把登录一起卡死），但降级要能被系统状态页看见；
- 恢复时要清掉故障记录，否则状态页永远显示"不可用"，运维会去查一个已经好了的问题。

不打真实 Redis：把模块里的 _client 换成假的，只验控制流。
"""
from __future__ import annotations

import redis
import pytest

from app.core import redis_client


# 模块导入时创建的那份真实客户端：fixture 每次进入都还原成它，避免"上一条用例把它置空"串味
_REAL_CLIENT = redis_client._client


class _FakeRedis:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.pings = 0

    def ping(self):
        self.pings += 1
        if self.fail:
            raise redis.ConnectionError("模拟连不上")
        return True


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """每个用例都从"没有故障记录、客户端完好"开始，结束后**无条件**还原。

    这是模块级全局状态（_client / _last_error），泄漏出去会让别的用例莫名降级：
    2026-11-20 的现场 —— 本文件某条用例把 _client 置成 None，还原时又用 monkeypatch
    与原始值混着写，结果 _client 一直是 None；后续 test_shares 的限流因此全部走
    "Redis 不可用"降级，share 域 fail-closed 直接 429，表现为"单跑全绿、整轮必红"。

    所以这里用 try/finally 直接赋值还原（不经 monkeypatch），并且**不假设进入时的状态**：
    模块导入时那份真实客户端存在 _REAL_CLIENT 里，每次进入都先还原成它。
    （不能用假客户端当默认值：真实客户端有 pipeline / delete 等方法，
    假实现只覆盖了本文件用到的 ping，别的用例会 AttributeError。）
    """
    saved_client, saved_error = redis_client._client, redis_client._last_error
    redis_client._client = _REAL_CLIENT
    redis_client._last_error = None
    try:
        yield
    finally:
        redis_client._client = saved_client if saved_client is not None else _REAL_CLIENT
        redis_client._last_error = saved_error


def test_get_redis_returns_shared_client(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "_client", fake)
    assert redis_client.get_redis() is fake


def test_get_redis_returns_none_when_init_failed(monkeypatch):
    """初始化失败时为 None：调用方据此放行，而不是抛异常把请求打死。"""
    monkeypatch.setattr(redis_client, "_client", None)
    assert redis_client.get_redis() is None


def test_mark_down_records_reason(monkeypatch):
    """故障要留下"哪一步失败、为什么"，否则状态页只有一句"Redis 不可用"，无从排查。

    注意两条 reason 的**来源不同**（别把两者混为一谈）：
    - mark_down 记的是"某次业务调用失败了什么"，存在 _last_error 里，只在没有客户端时作为兜底文案；
    - redis_status 有客户端时是**实时 ping**，失败时报的是 ping 的错误。
    这里客户端为 None，所以看到的是 mark_down 那条。
    """
    monkeypatch.setattr(redis_client, "_client", None)
    redis_client.mark_down("限流计数", redis.ConnectionError("连接被拒绝"))
    status = redis_client.redis_status()
    assert status["available"] is False
    assert "限流计数失败" in status["reason"]
    assert "连接被拒绝" in status["reason"]


def test_status_prefers_live_ping_over_recorded_reason(monkeypatch):
    """有客户端时以实时探活为准：mark_down 记的是历史，可能早就恢复了。"""
    monkeypatch.setattr(redis_client, "_client", _FakeRedis(fail=True))
    redis_client.mark_down("限流计数", redis.ConnectionError("历史故障"))
    status = redis_client.redis_status()
    assert "历史故障" not in status["reason"]
    assert "模拟连不上" in status["reason"]


def test_mark_up_clears_reason(monkeypatch):
    """恢复后必须清掉记录：留着会让运维去查一个已经好了的问题。"""
    monkeypatch.setattr(redis_client, "_client", _FakeRedis())
    redis_client.mark_down("限流计数", redis.ConnectionError("x"))
    redis_client.mark_up()
    assert redis_client._last_error is None
    assert redis_client.redis_status() == {"available": True, "reason": None}


def test_status_reports_down_when_client_missing(monkeypatch):
    """客户端为 None 且没有故障记录：给"Redis 未配置"，不能只回一个空 reason。"""
    monkeypatch.setattr(redis_client, "_client", None)
    status = redis_client.redis_status()
    assert status["available"] is False
    assert status["reason"] == "Redis 未配置"


def test_status_pings_the_client(monkeypatch):
    """可用性是**实时探活**得出的，不能只看"客户端对象存在"（连接可能早就断了）。"""
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "_client", fake)
    redis_client.redis_status()
    assert fake.pings == 1


def test_status_translates_ping_failure(monkeypatch):
    monkeypatch.setattr(redis_client, "_client", _FakeRedis(fail=True))
    status = redis_client.redis_status()
    assert status["available"] is False
    assert "Redis 不可用" in status["reason"]
