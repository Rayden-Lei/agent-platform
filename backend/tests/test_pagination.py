"""列表分页契约：参数边界、上限截断、total 与 items 一致、筛选下推、枚举校验、运行记录汇总。"""
import pytest


def test_page_size_is_capped_not_rejected(client, auth_headers):
    r = client.get("/api/v1/runs?page_size=500", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["page_size"] == 100
    assert len(r.json()["items"]) <= 100


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page=-1", "page=abc"])
def test_invalid_page_params_return_422(client, auth_headers, query):
    r = client.get(f"/api/v1/tools?{query}", headers=auth_headers)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("path", ["/api/v1/runs?status=bogus", "/api/v1/runs?run_type=bogus", "/api/v1/agents?status=bogus"])
def test_invalid_enum_filter_returns_422(client, auth_headers, path):
    r = client.get(path, headers=auth_headers)
    assert r.status_code == 422, r.text


def test_total_and_pages_are_consistent(client, auth_headers):
    ids = []
    try:
        for i in range(3):
            t = client.post("/api/v1/tools", headers=auth_headers, json={
                "name": f"pytest-page-{i}", "description": "分页用例", "type": "builtin", "config": {}, "timeout": 30,
            })
            assert t.status_code == 200, t.text
            ids.append(t.json()["id"])

        p1 = client.get("/api/v1/tools?q=pytest-page-&page_size=2&page=1", headers=auth_headers).json()
        assert p1["total"] == 3 and p1["page"] == 1 and p1["page_size"] == 2
        assert [x["name"] for x in p1["items"]] == ["pytest-page-0", "pytest-page-1"]

        p2 = client.get("/api/v1/tools?q=pytest-page-&page_size=2&page=2", headers=auth_headers).json()
        assert p2["total"] == 3 and [x["name"] for x in p2["items"]] == ["pytest-page-2"]

        beyond = client.get("/api/v1/tools?q=pytest-page-&page_size=2&page=5", headers=auth_headers).json()
        assert beyond["total"] == 3 and beyond["items"] == []
    finally:
        for tid in ids:
            client.delete(f"/api/v1/tools/{tid}", headers=auth_headers)


def test_agent_status_filter_is_applied_server_side(client, auth_headers):
    published = client.get("/api/v1/agents?status=published&page_size=100", headers=auth_headers).json()
    assert all(a["status"] == "published" for a in published["items"])
    draft = client.get("/api/v1/agents?status=draft&page_size=100", headers=auth_headers).json()
    assert all(a["status"] == "draft" for a in draft["items"])


def test_runs_summary_shape_matches_status_counts(client, auth_headers):
    s = client.get("/api/v1/runs/summary", headers=auth_headers)
    assert s.status_code == 200, s.text
    body = s.json()
    for key in ("total", "running", "success", "failed", "cancelled", "awaiting_review", "total_tokens", "total_cost"):
        assert key in body, key
    assert body["total"] == body["running"] + body["success"] + body["failed"] + body["cancelled"] + body["awaiting_review"]
    assert body["total"] == client.get("/api/v1/runs?page_size=1", headers=auth_headers).json()["total"]


def test_list_endpoints_all_return_page_envelope(client, auth_headers):
    paths = [
        "/api/v1/users", "/api/v1/models", "/api/v1/agents", "/api/v1/conversations", "/api/v1/tools",
        "/api/v1/knowledge-bases", "/api/v1/workflows", "/api/v1/runs", "/api/v1/audit-logs",
        "/api/v1/api-keys", "/api/v1/schedules",
    ]
    for path in paths:
        r = client.get(path, headers=auth_headers)
        assert r.status_code == 200, f"{path}: {r.text}"
        body = r.json()
        assert set(body) >= {"items", "total", "page", "page_size"}, path
        assert isinstance(body["items"], list), path
