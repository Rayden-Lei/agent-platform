"""工具凭据托管与审计（docs/15 RS-06，AC-032）：凭据加密存、任何接口不回传；执行时按鉴权方式带上；错误文案打码；增删改都留痕。

上游一律用 httpx.MockTransport 打桩，不发网络请求。
"""
import json
import uuid

import httpx
import pytest

from app.db.models import AuditLog
from app.db.session import SessionLocal
from app.tools import executor

TOKEN = "sk-pytest-" + uuid.uuid4().hex  # 每次不同，全文搜索它不会撞上别的数据


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def upstream(monkeypatch) -> dict:
    """上游桩：记下收到的请求；status 可改（测试错误打码）。"""
    state = {"requests": [], "status": 200}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return httpx.Response(state["status"], json={"ok": True})

    monkeypatch.setattr(executor.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return state


@pytest.fixture
def make_tool(client, auth_headers):
    created: list[int] = []

    def _make(**body):
        payload = {"name": "pytest_secret_" + _uid(), "description": "x", "type": "http", "config": {"url": "http://upstream.test/q", "method": "GET"}, **body}
        r = client.post("/api/v1/tools", headers=auth_headers, json=payload)
        if r.status_code == 200:
            created.append(r.json()["id"])
        return r

    yield _make
    for tid in created:
        client.delete(f"/api/v1/tools/{tid}", headers=auth_headers)


def _audits(tool_id: int) -> list[AuditLog]:
    db = SessionLocal()
    try:
        return db.query(AuditLog).filter(AuditLog.resource == "tool", AuditLog.resource_id == tool_id).order_by(AuditLog.id).all()
    finally:
        db.close()


def test_bearer_secret_is_never_returned_but_used_on_call(client, auth_headers, make_tool, upstream):
    r = make_tool(auth={"type": "bearer"}, secret=TOKEN)
    assert r.status_code == 200, r.text
    tool = r.json()
    assert tool["auth"] == {"type": "bearer", "location": None, "name": None, "has_secret": True}
    body = {k: tool[k] for k in ("name", "description", "type", "config", "timeout")}
    responses = [r.text, client.get("/api/v1/tools", headers=auth_headers, params={"q": tool["name"]}).text,
                 client.get(f"/api/v1/tools/{tool['id']}", headers=auth_headers).text,
                 client.put(f"/api/v1/tools/{tool['id']}", headers=auth_headers, json={**body, "auth": {"type": "bearer"}}).text]
    assert all(TOKEN not in text for text in responses)
    assert client.post(f"/api/v1/tools/{tool['id']}/test", headers=auth_headers, json={"args": {}}).status_code == 200
    assert upstream["requests"][-1].headers["authorization"] == f"Bearer {TOKEN}"  # 编辑时没填凭据：沿用


def test_clear_secret_stops_sending_auth(client, auth_headers, make_tool, upstream):
    tool = make_tool(auth={"type": "api_key", "location": "header", "name": "X-Api-Key"}, secret=TOKEN).json()
    body = {k: tool[k] for k in ("name", "description", "type", "config", "timeout")}
    cleared = client.put(f"/api/v1/tools/{tool['id']}", headers=auth_headers, json={**body, "auth": {"type": "none"}, "clear_secret": True})
    assert cleared.status_code == 200 and cleared.json()["auth"]["has_secret"] is False
    client.post(f"/api/v1/tools/{tool['id']}/test", headers=auth_headers, json={"args": {}})
    assert "x-api-key" not in upstream["requests"][-1].headers and "authorization" not in upstream["requests"][-1].headers


def test_query_api_key_is_sent_and_scrubbed_from_errors(client, auth_headers, make_tool, upstream):
    config = {"url": "http://upstream.test/q", "method": "GET", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}
    tool = make_tool(config=config, auth={"type": "api_key", "location": "query", "name": "api_key"}, secret=TOKEN).json()
    upstream["status"] = 401
    result = client.post(f"/api/v1/tools/{tool['id']}/test", headers=auth_headers, json={"args": {"q": "1"}}).json()["data"]["result"]
    assert upstream["requests"][-1].url.params["api_key"] == TOKEN and upstream["requests"][-1].url.params["q"] == "1"
    assert "error" in result and TOKEN not in json.dumps(result) and "***" in result["error"]  # httpx 的错误文案带完整地址


@pytest.mark.parametrize("body,status", [
    ({"config": {"url": "http://upstream.test/q", "headers": {"Authorization": "Bearer x"}}}, 422),
    ({"config": {"url": "http://upstream.test/q", "headers": {"X-Access-Token": "x"}}}, 422),
    ({"auth": {"type": "oauth"}, "secret": "x"}, 422),
    ({"auth": {"type": "api_key"}, "secret": "x"}, 422),
    ({"auth": {"type": "bearer"}}, 400),
    ({"auth": {"type": "none"}, "secret": "x"}, 400),
    ({"type": "builtin", "config": {}, "auth": {"type": "bearer"}, "secret": "x"}, 400),
])
def test_bad_auth_config_is_rejected(make_tool, body, status):
    assert make_tool(**body).status_code == status


def test_audit_records_changes_without_the_secret(client, auth_headers, make_tool):
    tool = make_tool(auth={"type": "bearer"}, secret=TOKEN).json()
    body = {k: tool[k] for k in ("name", "description", "type", "config", "timeout")}
    other = "sk-pytest-new-" + uuid.uuid4().hex
    client.put(f"/api/v1/tools/{tool['id']}", headers=auth_headers, json={**body, "description": "改了描述", "auth": {"type": "bearer"}, "secret": other})
    client.post(f"/api/v1/tools/{tool['id']}/toggle", headers=auth_headers)
    client.delete(f"/api/v1/tools/{tool['id']}", headers=auth_headers)
    logs = _audits(tool["id"])
    assert [a.action for a in logs] == ["create", "update", "disable", "delete"]
    update = logs[1].detail
    assert update["changed"] == ["description"] and update["secret"] == "已更换"
    assert all(TOKEN not in json.dumps(a.detail) and other not in json.dumps(a.detail) for a in logs)


def test_model_update_is_audited(client, auth_headers):
    m = client.post("/api/v1/models", headers=auth_headers, json={"name": "pytest-audit-model-" + _uid(), "provider": "openai", "api_base": "http://upstream.test/v1",
                                                                    "api_key": "sk-old", "model_name": "x", "default_params": {}}).json()
    try:
        body = {k: m[k] for k in ("name", "provider", "model_name", "default_params")}
        assert client.put(f"/api/v1/models/{m['id']}", headers=auth_headers, json={**body, "api_base": "http://other.test/v1", "api_key": "sk-new-secret"}).status_code == 200
        db = SessionLocal()
        try:
            log = db.query(AuditLog).filter(AuditLog.resource == "model", AuditLog.resource_id == m["id"], AuditLog.action == "update").one()
        finally:
            db.close()
        assert log.detail["changed"] == ["api_base"] and log.detail["api_key"] == "已更换" and "sk-new-secret" not in json.dumps(log.detail)
    finally:
        client.delete(f"/api/v1/models/{m['id']}", headers=auth_headers)
