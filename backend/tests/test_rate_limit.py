"""入口限流的用户与匿名维度、响应头、状态汇报（`12-差距补齐开发计划.md` 1.3，FR-025）。

API Key 维度的用例在 test_api_keys.py。限流默认在测试里关闭（conftest），每个用例自己打开并固定时钟。
"""
import uuid

from app.config import settings
from app.core import rate_limiter, redis_client

LOGIN = {"username": "admin", "password": "admin123"}


def _enable(monkeypatch, *, user_limit: int = 300, ip_limit: int = 20, api_key_limit: int = 60):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_USER_PER_MINUTE", user_limit)
    monkeypatch.setattr(settings, "RATE_LIMIT_IP_PER_MINUTE", ip_limit)
    monkeypatch.setattr(settings, "RATE_LIMIT_API_KEY_PER_MINUTE", api_key_limit)
    monkeypatch.setattr(rate_limiter, "_clock", lambda: 1_800_000_000.0)


def _fresh_user_headers(client, auth_headers) -> tuple[int, dict]:
    """用新建用户计数：admin 的计数键在固定时钟下会跨用例累积（TTL 65 秒）。

    必须在打开限流之前调用：建用户与登录都会被计入 admin / 新用户的额度。
    """
    username = "pytest-rl-" + uuid.uuid4().hex[:6]
    u = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "pytest-Passw0rd", "role": "caller"})
    assert u.status_code == 200, u.text
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "pytest-Passw0rd"}).json()["token"]
    return u.json()["id"], {"Authorization": "Bearer " + token}


def _cleanup_user(client, auth_headers, monkeypatch, uid: int) -> None:
    """清理前先关限流：admin 的额度可能已被本用例耗尽，否则删用户会 429 留下垃圾数据。"""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    client.delete(f"/api/v1/users/{uid}", headers=auth_headers)


def test_user_rate_limit_returns_429_with_retry_after(client, auth_headers, monkeypatch):
    uid, headers = _fresh_user_headers(client, auth_headers)
    _enable(monkeypatch, user_limit=2)
    try:
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        r = client.get("/api/v1/auth/me", headers=headers)
        assert r.status_code == 429, r.text
        assert "请求过于频繁" in r.json()["detail"]
        assert r.json()["trace_id"] == r.headers["x-request-id"]
        assert 1 <= int(r.headers["retry-after"]) <= 60
        assert r.headers["x-ratelimit-limit"] == "2"
        assert r.headers["x-ratelimit-remaining"] == "0"
    finally:
        _cleanup_user(client, auth_headers, monkeypatch, uid)


def test_allowed_response_carries_rate_limit_headers(client, auth_headers, monkeypatch):
    uid, headers = _fresh_user_headers(client, auth_headers)
    _enable(monkeypatch, user_limit=5)
    try:
        r = client.get("/api/v1/auth/me", headers=headers)
        assert r.status_code == 200
        assert r.headers["x-ratelimit-limit"] == "5"
        assert r.headers["x-ratelimit-remaining"] == "4"
        assert "retry-after" not in r.headers
    finally:
        _cleanup_user(client, auth_headers, monkeypatch, uid)


def test_invalid_token_does_not_consume_user_quota(client, auth_headers, monkeypatch):
    """先鉴权再计数：伪造 token 的请求不能把真实用户的额度打光。"""
    uid, headers = _fresh_user_headers(client, auth_headers)
    _enable(monkeypatch, user_limit=1)
    try:
        for _ in range(3):
            assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    finally:
        _cleanup_user(client, auth_headers, monkeypatch, uid)


def test_anonymous_login_rate_limited_by_ip(client, auth_headers, monkeypatch, client_from):
    _enable(monkeypatch, ip_limit=2)
    ip = "10.77." + ".".join(str(int(b)) for b in uuid.uuid4().bytes[:2])  # 每次运行不同来源，避免固定时钟下计数残留
    c = client_from(ip)
    assert c.post("/api/v1/auth/login", json=LOGIN).status_code == 200
    assert c.post("/api/v1/auth/login", json=LOGIN).status_code == 200
    r = c.post("/api/v1/auth/login", json=LOGIN)
    assert r.status_code == 429, r.text
    assert r.headers["x-ratelimit-limit"] == "2"
    # 换一个来源不受影响
    assert client_from("10.78.0.1").post("/api/v1/auth/login", json=LOGIN).status_code == 200


def test_api_key_429_carries_retry_after(client, auth_headers, monkeypatch):
    _enable(monkeypatch, api_key_limit=1)
    k = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-rl-header"}).json()
    try:
        bearer = {"Authorization": "Bearer " + k["key"]}
        ok = client.get("/api/v1/auth/me", headers=bearer)
        assert ok.status_code == 200
        assert ok.headers["x-ratelimit-remaining"] == "0"
        r = client.get("/api/v1/auth/me", headers=bearer)
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_status_reports_rate_limit_and_degrades_on_redis_failure(client, auth_headers, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(redis_client, "redis_status", lambda: {"available": False, "reason": "模拟 Redis 不可用"})
    body = client.get("/api/v1/system/status", headers=auth_headers).json()
    assert body["rate_limit"]["enabled"] is False
    assert body["rate_limit"]["configured"] is True
    assert "模拟 Redis 不可用" in body["rate_limit"]["reason"]
    assert body["rate_limit"]["api_key_per_minute"] == 60
    assert "rate_limit" in [d["item"] for d in body["degraded"]]


def test_status_when_rate_limit_disabled_by_config_is_not_degraded(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    body = client.get("/api/v1/system/status", headers=auth_headers).json()
    assert body["rate_limit"]["enabled"] is False
    assert body["rate_limit"]["configured"] is False
    assert "rate_limit" not in [d["item"] for d in body["degraded"]]


def test_status_when_rate_limit_healthy(client, auth_headers, monkeypatch):
    _enable(monkeypatch)
    body = client.get("/api/v1/system/status", headers=auth_headers).json()
    assert body["rate_limit"]["enabled"] is True
    assert body["rate_limit"]["reason"] is None
    assert "rate_limit" not in [d["item"] for d in body["degraded"]]
