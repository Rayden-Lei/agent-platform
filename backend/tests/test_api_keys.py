"""API Key 鉴权：以归属用户身份调用、配额扣减、管理接口拒绝、无效 / 停用 / 删除的 Key 被拒；
入口治理（`12-差距补齐开发计划.md` 1.2）：来源白名单、单 Key 限速、按创建人隔离、编辑接口；
生命周期（docs/15 PB-11）：有效期、轮换、配额"不限"语义、被拒留痕。"""
import uuid
from datetime import datetime, timedelta, timezone

import redis

from app.config import settings
from app.core import rate_limiter, redis_client
from app.db.models import ApiKey, AuditLog
from app.db.session import SessionLocal
from tests.conftest import publish_workflow

START_END_GRAPH = {
    "nodes": [{"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}}, {"id": "e", "type": "end", "config": {}}],
    "edges": [{"from": "s", "to": "e"}],
}


def _create_key(client, auth_headers, scope: dict, quota=1000, name="pytest-api-key"):
    """scope 是作用域（至少一项非空）；不关心作用域的用例传 conftest 的 key_scope。"""
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": name, "quota": quota, **scope})
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(key: str) -> dict:
    return {"Authorization": "Bearer " + key}


def _key_row(client, auth_headers, key_id: int) -> dict:
    return next(k for k in client.get("/api/v1/api-keys", headers=auth_headers).json()["items"] if k["id"] == key_id)


def test_api_key_acts_as_owner_and_counts_usage(client, auth_headers, key_scope):
    k = _create_key(client, auth_headers, key_scope)
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


def test_api_key_rejected_on_management_endpoints(client, auth_headers, key_scope):
    k = _create_key(client, auth_headers, key_scope)
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
    # 运行读线上版本（FR-075）：没发布的工作流对 Key 一律 403「工作流未发布」
    publish_workflow(client, auth_headers, wid)
    k = _create_key(client, auth_headers, {"workflow_ids": [wid]})
    try:
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=_bearer(k["key"]), json={"inputs": {"input": "hello"}})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "success"
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_api_key_invalid_disabled_deleted_are_rejected(client, auth_headers, key_scope):
    bogus = "ak_" + "0" * 32
    r = client.get("/api/v1/auth/me", headers=_bearer(bogus))
    assert r.status_code == 401
    assert "API Key" in r.json()["detail"]

    k = _create_key(client, auth_headers, key_scope)
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


def test_api_key_quota_exhausted_returns_429(client, auth_headers, key_scope):
    k = _create_key(client, auth_headers, key_scope, quota=2)
    try:
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        r = client.get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert r.status_code == 429
        assert "配额" in r.json()["detail"]
        assert _key_row(client, auth_headers, k["id"])["used"] == 2  # 超额请求不再累加
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


# ---------- 生命周期：有效期与轮换（docs/15 PB-11，2026-11-18） ----------

def _set_expires_at(key_id: int, value: datetime | None) -> None:
    """直接改库里的有效期：接口只收未来时间（422），造"已过期"的现场只能从库里改。"""
    db = SessionLocal()
    try:
        row = db.get(ApiKey, key_id)
        assert row is not None
        row.expires_at = value
        db.commit()
    finally:
        db.close()


def _create_key_with(client, auth_headers, scope: dict, **extra) -> dict:
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-lifecycle", **scope, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_expired_key_is_rejected_401_without_consuming_quota(client, auth_headers, key_scope):
    """过期 Key 调 401 且文案明确是"已过期"（与"已停用"同一口径），used 不变 —— 过期判定在扣配额之前。"""
    k = _create_key(client, auth_headers, key_scope, name="pytest-expired")
    try:
        _set_expires_at(k["id"], datetime.now(timezone.utc) - timedelta(minutes=1))
        r = client.get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert r.status_code == 401, r.text
        assert "已过期" in r.json()["detail"]
        row = _key_row(client, auth_headers, k["id"])
        assert row["used"] == 0, "过期 Key 不该消耗配额"
        assert row["is_expired"] is True
        audit = _latest_audit("api_key_expired", k["id"])
        assert audit is not None and audit.detail["reason"] == "API Key 已过期"
        assert "key_prefix" in audit.detail and k["key"] not in str(audit.detail)
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_key_with_future_expiry_works(client, auth_headers, key_scope):
    """未到期的 Key 正常可用；列表里能看出有效期与 is_expired=False。"""
    expires = datetime.now(timezone.utc) + timedelta(hours=2)
    k = _create_key_with(client, auth_headers, key_scope, expires_at=expires.isoformat())
    try:
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        row = _key_row(client, auth_headers, k["id"])
        assert row["is_expired"] is False
        assert row["expires_at"] is not None
        assert row["used"] == 1
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_key_without_expiry_never_expires(client, auth_headers, key_scope):
    """不传 expires_at = 永不过期（存量 Key 迁移后都是这个状态），is_expired 为 False。"""
    k = _create_key(client, auth_headers, key_scope, name="pytest-no-expiry")
    try:
        row = _key_row(client, auth_headers, k["id"])
        assert row["expires_at"] is None and row["is_expired"] is False
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_expires_at_in_past_or_naive_returns_422(client, auth_headers, key_scope):
    """有效期必须是未来时间、且带时区（服务端唯一权威，不靠前端日期选择器）。"""
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-past", "expires_at": past, **key_scope})
    assert r.status_code == 422, r.text
    assert "未来时间" in r.text

    k = _create_key(client, auth_headers, key_scope, name="pytest-past-put")
    try:
        r = client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"expires_at": past})
        assert r.status_code == 422, r.text
        assert "未来时间" in r.text
        # 不带时区的时间不猜时区
        naive = client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"expires_at": "2030-01-01T00:00:00"})
        assert naive.status_code == 422, naive.text
        assert "时区" in naive.text
        # 被拒的请求没有改动库里的值
        assert _key_row(client, auth_headers, k["id"])["expires_at"] is None
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_update_expires_at_and_clear_it(client, auth_headers, key_scope):
    """PUT 能设有效期，显式传 null 能清除（永不过期）；审计 update 里记了改动的字段。"""
    k = _create_key(client, auth_headers, key_scope, name="pytest-expiry-update")
    try:
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        r = client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"expires_at": expires.isoformat()})
        assert r.status_code == 200, r.text
        assert r.json()["expires_at"] is not None and r.json()["is_expired"] is False
        assert "expires_at" in _latest_audit("update", k["id"]).detail["changed"]

        cleared = client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"expires_at": None})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["expires_at"] is None
        # 不传这个字段时保持不变（设置后不会被"未传"清掉）
        again = client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"expires_at": expires.isoformat()})
        assert again.status_code == 200
        kept = client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"name": "pytest-expiry-kept"})
        assert kept.json()["expires_at"] is not None
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_rotate_invalidates_old_plaintext_and_keeps_settings(client, auth_headers, key_scope):
    """轮换：旧明文立即 401，新明文可用；其余设置与累计用量不变；审计有 rotate 且不含明文。"""
    expires = datetime.now(timezone.utc) + timedelta(days=3)
    k = _create_key_with(client, auth_headers, key_scope, quota=7, rate_limit_per_minute=30,
                         allowed_ips=["10.0.0.0/8"], expires_at=expires.isoformat())
    try:
        # 先正常用一次，确认轮换不会重置累计用量
        db = SessionLocal()
        try:
            row = db.get(ApiKey, k["id"])
            row.allowed_ips = []
            db.commit()
        finally:
            db.close()
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200

        r = client.post(f"/api/v1/api-keys/{k['id']}/rotate", headers=auth_headers)
        assert r.status_code == 200, r.text
        rotated = r.json()
        assert rotated["key"] != k["key"] and rotated["key"].startswith("ak_")
        assert rotated["id"] == k["id"]
        assert rotated["name"] == k["name"] and rotated["quota"] == 7
        assert rotated["rate_limit_per_minute"] == 30
        assert rotated["agent_ids"] == k["agent_ids"] and rotated["workflow_ids"] == k["workflow_ids"]
        assert rotated["expires_at"] is not None
        assert rotated["used"] == 1, "轮换不改身份，累计用量保留"
        assert rotated["key_prefix"] != k["key_prefix"]

        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 401
        assert client.get("/api/v1/auth/me", headers=_bearer(rotated["key"])).status_code == 200

        audit = _latest_audit("rotate", k["id"])
        assert audit is not None
        assert audit.detail["old_key_prefix"] == k["key_prefix"]
        assert k["key"] not in str(audit.detail) and rotated["key"] not in str(audit.detail)
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_developer_cannot_rotate_others_key(client, auth_headers, key_scope):
    """developer 轮换他人创建的 Key → 404（不暴露存在性），旧明文照常可用。"""
    dev_id, dev_headers = _developer(client, auth_headers)
    admin_key = _create_key(client, auth_headers, key_scope, name="pytest-rotate-others")
    try:
        assert client.post(f"/api/v1/api-keys/{admin_key['id']}/rotate", headers=dev_headers).status_code == 404
        assert client.get("/api/v1/auth/me", headers=_bearer(admin_key["key"])).status_code == 200
    finally:
        client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=auth_headers)
        client.delete(f"/api/v1/users/{dev_id}", headers=auth_headers)


def test_rotate_unknown_key_returns_404(client, auth_headers):
    assert client.post("/api/v1/api-keys/99999999/rotate", headers=auth_headers).status_code == 404


def test_quota_null_means_unlimited(client, auth_headers, key_scope):
    """quota 为空 = 不限次数（docs/15 PB-11）：连续调用不被配额拦；quota=0 仍是一次都调不了。"""
    unlimited = _create_key_with(client, auth_headers, key_scope, quota=None, name="pytest-quota-null")
    zero = _create_key_with(client, auth_headers, key_scope, quota=0, name="pytest-quota-zero")
    try:
        assert unlimited["quota"] is None
        for _ in range(3):
            assert client.get("/api/v1/auth/me", headers=_bearer(unlimited["key"])).status_code == 200
        assert _key_row(client, auth_headers, unlimited["id"])["used"] == 3

        r = client.get("/api/v1/auth/me", headers=_bearer(zero["key"]))
        assert r.status_code == 429 and "配额" in r.json()["detail"]
        assert _key_row(client, auth_headers, zero["id"])["used"] == 0
    finally:
        client.delete(f"/api/v1/api-keys/{unlimited['id']}", headers=auth_headers)
        client.delete(f"/api/v1/api-keys/{zero['id']}", headers=auth_headers)


# ---------- 被拒留痕（docs/15 PB-11）：过期 / 停用 / 越权 ----------

def test_disabled_key_rejection_is_audited(client, auth_headers, key_scope):
    """停用的 Key 被拒要留痕：能回答"谁在什么时候停用了 Key、之后还有谁在调"。"""
    k = _create_key(client, auth_headers, key_scope, name="pytest-audit-disabled")
    try:
        assert client.post(f"/api/v1/api-keys/{k['id']}/toggle", headers=auth_headers).json()["is_enabled"] is False
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 401
        audit = _latest_audit("api_key_disabled", k["id"])
        assert audit is not None and audit.detail["reason"] == "API Key 已停用"
        assert k["key"] not in str(audit.detail)
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_scope_rejection_logs_key_id_and_reason(client, auth_headers, caplog):
    """越权被拒记结构化日志：带 key id 与资源 id，不带任何密钥片段。"""
    w = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-audit-scope-wf", "description": "", "graph": START_END_GRAPH})
    assert w.status_code == 200, w.text
    wid = w.json()["id"]
    other = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-audit-scope-wf2", "description": "", "graph": START_END_GRAPH})
    other_id = other.json()["id"]
    k = _create_key(client, auth_headers, {"workflow_ids": [wid]}, name="pytest-audit-scope")
    try:
        with caplog.at_level("WARNING", logger="app.services.api_key_service"):
            r = client.get(f"/api/v1/workflows/{other_id}/parameters", headers=_bearer(k["key"]))
        assert r.status_code == 403, r.text
        line = next((x for x in caplog.messages if "越权被拒" in x), None)
        assert line is not None
        assert f"key_id={k['id']}" in line and f"workflow_id={other_id}" in line
        assert k["key"] not in line
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{other_id}", headers=auth_headers)


def test_lifecycle_actions_are_audited(client, auth_headers, key_scope):
    """增删改启停轮换都写审计（docs/15 PB-11 与 OP-05）：detail 只含前缀，不含明文与哈希。"""
    k = _create_key(client, auth_headers, key_scope, name="pytest-audit-lifecycle")
    try:
        assert _latest_audit("create", k["id"]) is not None
        assert client.put(f"/api/v1/api-keys/{k['id']}", headers=auth_headers, json={"name": "pytest-audit-lifecycle-2"}).status_code == 200
        assert _latest_audit("update", k["id"]) is not None
        assert client.post(f"/api/v1/api-keys/{k['id']}/toggle", headers=auth_headers).status_code == 200
        assert _latest_audit("disable", k["id"]) is not None
        assert client.post(f"/api/v1/api-keys/{k['id']}/toggle", headers=auth_headers).status_code == 200
        assert _latest_audit("enable", k["id"]) is not None
        assert client.post(f"/api/v1/api-keys/{k['id']}/rotate", headers=auth_headers).status_code == 200
        assert _latest_audit("rotate", k["id"]) is not None
        assert client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers).status_code == 200
        deleted = _latest_audit("delete", k["id"])
        assert deleted is not None and deleted.detail["name"] == "pytest-audit-lifecycle-2"
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


def test_allowlist_rejects_other_ip_without_consuming_quota(client, auth_headers, client_from, key_scope):
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-allowlist", "allowed_ips": ["10.0.0.0/8"], **key_scope})
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


def test_empty_allowlist_accepts_any_ip(client, auth_headers, client_from, key_scope):
    k = _create_key(client, auth_headers, key_scope)
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


def test_per_key_rate_limit_returns_429_without_consuming_quota(client, auth_headers, monkeypatch, key_scope):
    _enable_rate_limit(monkeypatch)
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-ratelimit", "rate_limit_per_minute": 2, **key_scope})
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


def test_rate_limit_zero_uses_global_default(client, auth_headers, monkeypatch, key_scope):
    _enable_rate_limit(monkeypatch, api_key_default=1)
    k = _create_key(client, auth_headers, key_scope, name="pytest-ratelimit-default")
    assert k["rate_limit_per_minute"] == 0
    try:
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 429
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_rate_limit_allows_when_redis_down(client, auth_headers, monkeypatch, key_scope):
    """Redis 故障时放行（可用性优先），并把故障原因记下来供状态接口暴露。"""
    _enable_rate_limit(monkeypatch, api_key_default=1)

    class _DownRedis:
        def pipeline(self):
            raise redis.ConnectionError("模拟 Redis 不可用")

    monkeypatch.setattr(redis_client, "get_redis", lambda: _DownRedis())
    monkeypatch.setattr(redis_client, "_last_error", None)
    k = _create_key(client, auth_headers, key_scope, name="pytest-ratelimit-redis-down")
    try:
        for _ in range(3):
            assert client.get("/api/v1/auth/me", headers=_bearer(k["key"])).status_code == 200
        assert _key_row(client, auth_headers, k["id"])["used"] == 3
        assert "模拟 Redis 不可用" in redis_client._last_error
    finally:
        client.delete(f"/api/v1/api-keys/{k['id']}", headers=auth_headers)


def test_rate_limit_disabled_by_config_never_limits(client, auth_headers, monkeypatch, key_scope):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    r = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-ratelimit-off", "rate_limit_per_minute": 1, **key_scope})
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


def test_developer_sees_only_own_keys(client, auth_headers, key_scope):
    dev_id, dev_headers = _developer(client, auth_headers)
    admin_key = _create_key(client, auth_headers, key_scope, name="pytest-admin-owned")
    try:
        dev_key = _create_key(client, dev_headers, key_scope, name="pytest-dev-owned")
        dev_ids = {k["id"] for k in client.get("/api/v1/api-keys", headers=dev_headers).json()["items"]}
        assert dev_key["id"] in dev_ids
        assert admin_key["id"] not in dev_ids
        admin_ids = {k["id"] for k in client.get("/api/v1/api-keys", headers=auth_headers, params={"page_size": 100}).json()["items"]}
        assert {dev_key["id"], admin_key["id"]} <= admin_ids
    finally:
        client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=auth_headers)
        client.delete(f"/api/v1/users/{dev_id}", headers=auth_headers)


def test_developer_cannot_modify_toggle_or_delete_others_key(client, auth_headers, key_scope):
    dev_id, dev_headers = _developer(client, auth_headers)
    admin_key = _create_key(client, auth_headers, key_scope, name="pytest-admin-owned-2")
    try:
        assert client.put(f"/api/v1/api-keys/{admin_key['id']}", headers=dev_headers, json={"name": "x"}).status_code == 404
        assert client.post(f"/api/v1/api-keys/{admin_key['id']}/toggle", headers=dev_headers).status_code == 404
        assert client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=dev_headers).status_code == 404
        assert _key_row(client, auth_headers, admin_key["id"])["is_enabled"] is True  # 没被 developer 动过

        dev_key = _create_key(client, dev_headers, key_scope, name="pytest-dev-owned-2")
        assert client.post(f"/api/v1/api-keys/{dev_key['id']}/toggle", headers=auth_headers).status_code == 200  # admin 不受限
    finally:
        client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=auth_headers)
        client.delete(f"/api/v1/users/{dev_id}", headers=auth_headers)


def test_update_api_key_fields(client, auth_headers, key_scope):
    k = _create_key(client, auth_headers, key_scope, name="pytest-update")
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
