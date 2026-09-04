"""API Key 鉴权：以归属用户身份调用、配额扣减、管理接口拒绝、无效 / 停用 / 删除的 Key 被拒。"""

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
    return next(k for k in client.get("/api/v1/api-keys", headers=auth_headers).json() if k["id"] == key_id)


def test_api_key_acts_as_owner_and_counts_usage(client, auth_headers):
    k = _create_key(client, auth_headers)
    try:
        owner = client.get("/api/v1/auth/me", headers=auth_headers).json()

        me = client.get("/api/v1/auth/me", headers=_bearer(k["key"]))
        assert me.status_code == 200, me.text
        assert me.json()["id"] == owner["id"]

        conv = client.get("/api/v1/conversations", headers=_bearer(k["key"]))
        assert conv.status_code == 200, conv.text
        assert isinstance(conv.json(), list)

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
