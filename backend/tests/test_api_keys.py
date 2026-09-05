"""API Key 鉴权：以归属用户身份调用、配额扣减、管理接口拒绝、无效 / 停用 / 删除的 Key 被拒；
入口治理（`12-差距补齐开发计划.md` 1.2）：来源白名单、单 Key 限速、按创建人隔离、编辑接口。"""
import uuid

import redis

from app.config import settings
from app.core import rate_limiter, redis_client
from app.db.models import AuditLog
from app.db.session import SessionLocal

START_END_GRAPH = {
    "nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "e", "type": "end", "config": {}}],
    "edges": [{"from": "s", "to": "e"}],
}


def _create_key(client, auth_headers, quota=1000, name="pytest-api-key"):
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": name, "quota": quota})
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(key: str) -> dict:
    return {"Authorization": "Bearer " + key}


def _key_row(client, auth_headers, key_id: int) -> dict:
    return next(k for k in client.get("/api/v1/api-keys", headers=auth_headers).json()["items"] if k["id"] == key_id)


def test_api_key_acts_as_owner_and_counts_usage(client, auth_headers):
    k = _create_key(client, auth_headers)
    try:
        owner = client.get("/api/v1/auth/me", headers=auth_headers).json()

        me = client.get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert me.status_code == 200, me.text
        assert me.json()["id"] == owner["id"]

        conv = client.get("/api/v1/conversations", headers=_bearer(k["key"]))
        assert conv.status_code == 200, conv.text
        assert isinstance(conv.json()["items"], list)

        row = _key_row(client, auth_headers, k["id"])
        assert row["used"] == 2
        assert row["last_used_at"] is not None
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_api_key_rejected_on_management_endpoints(client, auth_headers):
    k = _create_key(client, auth_headers)
    try:
        for path in ("/api/v1/agents", "/api/v1/models", "/api/v1/users", "/api/v1/api-keys", "/api/v1/workflows"):
            r = client.get(path, headers=_bearer(k["key"]))
            assert r.status_code == 403, f"{path}: {r.status_code} {r.text}"
            assert "API Key" in r.json()["detail"]
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_api_key_can_run_workflow(client, auth_headers):
    w = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-apikey-wf", "description": "", "graph": START_END_GRAPH})
    assert w.status_code == 200, w.text
    wid = w.json()["id"]
    k = _create_key(client, auth_headers)
    try:
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=_bearer(k["key"]), json={"input": "hello"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "success"
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_api_key_invalid_disabled_deleted_are_rejected(client, auth_headers):
    bogus = "ak_" + "0" * 32
    r = client.get("/api/v1/auth/me", headers=_bearer(bogus))
    assert r.status_code == 401
    assert "API Key" in r.json()["detail"]

    k = _create_key(client, auth_headers)
    try:
        t = client.post(f"/api/v1/api-keys/{k['id']}/toggle", headers=auth_headers)
        assert t.status_code == 200 and t.json()["is_enabled"] is False
        r = client.get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert r.status_code == 401
        assert "停用" in r.json()["detail"]
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)

    # 删除后同一明文不再可用
    assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 401


def test_api_key_quota_exhausted_returns_429(client, auth_headers):
    k = _create_key(client, auth_headers, quota=2)
    try:
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        r = client.get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert r.status_code == 429
        assert "配额" in r.json()["detail"]
        assert _key_row(client, auth_headers, k["id"])["used"] == 2  # 超额请求不再累加
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


# ---------- 来源白名单（FR-026） ----------

def _latest_audit(action: str, resource_id: int):
    db = SessionLocal()
    try:
        return (
            db.query(AuditLog)
            .filter(AuditLog.action == action, AuditLog.resource_id == resource_id)
            .order_by(AuditLog.id.desc())
            .first()
        )
    finally:
        db.close()


def test_allowlist_rejects_other_ip_without_consuming_quota(client, auth_headers, client_from):
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-allowlist", "allowed_ips": ["10.0.0.0/8"]})
    assert r.status_code == 200, r.text
    k = r.json()
    try:
        denied = client_from("192.168.1.5").get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert denied.status_code == 403, denied.text
        assert "不允许从该 IP" in denied.json()["detail"]
        assert _key_row(client, auth_headers, k["id"])["used"] == 0
        audit = _latest_audit("api_key_ip_rejected", k["id"])
        assert audit is not None
        assert audit.ip == "192.168.1.5"
        assert audit.detail["ip"] == "192.168.1.5"

        allowed = client_from("10.1.2.3").get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert allowed.status_code == 200, allowed.text
        assert _key_row(client, auth_headers, k["id"])["used"] == 1
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_empty_allowlist_accepts_any_ip(client, auth_headers, client_from):
    k = _create_key(client, auth_headers)
    try:
        assert client_from("8.8.8.8").get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_invalid_cidr_returns_422(client, auth_headers):
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-bad-cidr", "allowed_ips": ["10.0.0.0/8", "10.0.0.0/33"]})
    assert r.status_code == 422, r.text
    assert "第 2 项" in r.text


# ---------- 单 Key 限速（FR-025） ----------

def _enable_rate_limit(monkeypatch, api_key_default: int = 60):
    """打开限流并固定时钟，避免用例跨过自然分钟边界时计数被重置。"""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_API_KEY_PER_MINUTE", api_key_default)
    monkeypatch.setattr(rate_limiter, "_clock", lambda: 1_800_000_000.0)


def test_per_key_rate_limit_returns_429_without_consuming_quota(client, auth_headers, monkeypatch):
    _enable_rate_limit(monkeypatch)
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-ratelimit", "rate_limit_per_minute": 2})
    assert r.status_code == 200, r.text
    k = r.json()
    try:
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        limited = client.get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert limited.status_code == 429, limited.text
        assert "请求过于频繁" in limited.json()["detail"]
        assert _key_row(client, auth_headers, k["id"])["used"] == 2  # 被限流的请求不扣配额
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_rate_limit_zero_uses_global_default(client, auth_headers, monkeypatch):
    _enable_rate_limit(monkeypatch, api_key_default=1)
    k = _create_key(client, auth_headers, name="pytest-ratelimit-default")
    assert k["rate_limit_per_minute"] == 0
    try:
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 429
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_rate_limit_allows_when_redis_down(client, auth_headers, monkeypatch):
    """Redis 故障时放行（可用性优先），并把故障原因记下来供状态接口暴露。"""
    _enable_rate_limit(monkeypatch, api_key_default=1)

    class _DownRedis:
        def pipeline(self):
            raise redis.ConnectionError("模拟 Redis 不可用")

    monkeypatch.setattr(redis_client, "get_redis", lambda: _DownRedis())
    monkeypatch.setattr(redis_client, "_last_error", None)
    k = _create_key(client, auth_headers, name="pytest-ratelimit-redis-down")
    try:
        for _ in range(3):
            assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        assert _key_row(client, auth_headers, k["id"])["used"] == 3
        assert "模拟 Redis 不可用" in redis_client._last_error
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_rate_limit_disabled_by_config_never_limits(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-ratelimit-off", "rate_limit_per_minute": 1})
    k = r.json()
    try:
        for _ in range(3):
            assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


# ---------- 按创建人隔离与编辑（FR-026 评审决策 ①） ----------

def _developer(client, auth_headers) -> tuple[int, dict]:
    """新建一个 developer 并返回 (用户 id, 请求头)；调用方负责删除用户（级联删其 Key）。"""
    username = "pytest-dev-" + uuid.uuid4().hex[:6]
    u = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "pytest-Passw0rd", "role": "developer"})
    assert u.status_code == 200, u.text
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "pytest-Passw0rd"}).json()["token"]
    return u.json()["id"], {"Authorization": "Bearer " + token}


def test_developer_sees_only_own_keys(client, auth_headers):
    dev_id, dev_headers = _developer(client, auth_headers)
    admin_key = _create_key(client, auth_headers, name="pytest-admin-owned")
    try:
        dev_key = _create_key(client, dev_headers, name="pytest-dev-owned")
        dev_ids = {k["id"] for k in client.get("/api/v1/api-keys", headers=dev_headers).json()["items"]}
        assert dev_key["id"] in dev_ids
        assert admin_key["id"] not in dev_ids
        admin_ids = {k["id"] for k in client.get("/api/v1/api-keys", headers=auth_headers, params={"page_size": 100}).json()["items"]}
        assert {dev_key["id"], admin_key["id"]} <= admin_ids
    finally:
        client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=auth_headers)
        client.delete(f"/api/v1/users/{dev_id}", headers=auth_headers)


def test_developer_cannot_modify_toggle_or_delete_others_key(client, auth_headers):
    dev_id, dev_headers = _developer(client, auth_headers)
    admin_key = _create_key(client, auth_headers, name="pytest-admin-owned-2")
    try:
        assert client.put(f"/api/v1/api-keys/{admin_key['id']}", headers=dev_headers, json={"name": "x"}).status_code == 404
        assert client.post(f"/api/v1/api-keys/{admin_key['id']}/toggle", headers=dev_headers).status_code == 404
        assert client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=dev_headers).status_code == 404
        assert _key_row(client, auth_headers, admin_key["id"])["is_enabled"] is True  # 没被 developer 动过

        dev_key = _create_key(client, dev_headers, name="pytest-dev-owned-2")
        assert client.post(f"/api/v1/api-keys/{dev_key['id']}/toggle", headers=auth_headers).status_code == 200  # admin 不受限
    finally:
        client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=auth_headers)
        client.delete(f"/api/v1/users/{dev_id}", headers=auth_headers)


def test_update_api_key_fields(client, auth_headers):
    k = _create_key(client, auth_headers, name="pytest-update")
    try:
        r = client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={
            "name": "pytest-updated", "quota": 5, "allowed_ips": ["10.0.0.0/8", " 192.168.1.1 "], "rate_limit_per_minute": 120,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "pytest-updated"
        assert body["quota"] == 5
        assert body["allowed_ips"] == ["10.0.0.0/8", "192.168.1.1"]
        assert body["rate_limit_per_minute"] == 120
        assert "key" not in body and "key_hash" not in body

        partial = client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"quota": 9})
        assert partial.json()["quota"] == 9
        assert partial.json()["allowed_ips"] == ["10.0.0.0/8", "192.168.1.1"]  # 未传的字段不变

        assert client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"rate_limit_per_minute": 10001}).status_code == 422
        assert client.put("/api/v1/api-keys/99999999", headers=auth_headers, json={"quota": 1}).status_code == 404
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)
