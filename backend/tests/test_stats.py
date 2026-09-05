"""运营统计与运行记录深化（页面深度优化后端第 0 批）：按天趋势、概览、按模型 / 工作流聚合、
运行记录的排序 / 时间区间 / 关联名称 / 来源 / 耗时分布、节点日志时间戳、成本快照。"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.db.session import SessionLocal
from app.services import run_service

SIMPLE_GRAPH = {
    "nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "c", "type": "code", "config": {"code": "import time; time.sleep(0.05); result = 'ok'"}}, {"id": "e", "type": "end", "config": {}}],
    "edges": [{"from": "s", "to": "c"}, {"from": "c", "to": "e"}],
}


@pytest.fixture
def workflow(client, auth_headers):
    r = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-stats-wf-" + uuid.uuid4().hex[:6], "description": "", "graph": SIMPLE_GRAPH})
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"/api/v1/workflows/{r.json()['id']}", headers=auth_headers)


def _run(client, auth_headers, workflow_id: int) -> dict:
    r = client.post(f"/api/v1/workflows/{workflow_id}/run", headers=auth_headers, json={"input": "x"})
    assert r.status_code == 200 and r.json()["status"] == "success", r.text
    return r.json()


# ---------- 按天趋势 ----------

def test_stats_daily_fills_missing_days_and_orders_ascending(client, auth_headers, workflow):
    _run(client, auth_headers, workflow["id"])
    r = client.get("/api/v1/stats/runs/daily", headers=auth_headers, params={"days": 3, "workflow_id": workflow["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == 3 and body["timezone"] == settings.REPORT_TIMEZONE
    dates = [i["date"] for i in body["items"]]
    assert dates == sorted(dates) and len(dates) == 3
    today = datetime.now(ZoneInfo(settings.REPORT_TIMEZONE)).date().isoformat()
    assert dates[-1] == today
    assert body["items"][-1]["total"] >= 1 and body["items"][-1]["success"] >= 1
    assert body["items"][0]["total"] == 0 and body["items"][0]["success_rate"] is None  # 缺失日期补零


def test_stats_daily_clamps_days_and_rejects_invalid_values(client, auth_headers):
    assert client.get("/api/v1/stats/runs/daily", headers=auth_headers, params={"days": 1000}).json()["days"] == settings.STATS_MAX_DAYS
    assert client.get("/api/v1/stats/runs/daily", headers=auth_headers, params={"days": 0}).status_code == 422
    assert client.get("/api/v1/stats/runs/daily", headers=auth_headers, params={"run_type": "batch"}).status_code == 422


def test_stats_endpoints_forbid_caller_and_api_key(client, auth_headers):
    username = "pytest-stats-caller-" + uuid.uuid4().hex[:6]
    created = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "caller123", "role": "caller"}).json()
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-stats-key", "quota": 5}).json()
    try:
        token = client.post("/api/v1/auth/login", json={"username": username, "password": "caller123"}).json()["token"]
        for path in ("/api/v1/stats/overview", "/api/v1/stats/runs/daily", "/api/v1/stats/models", "/api/v1/stats/agents", "/api/v1/stats/workflows"):
            assert client.get(path, headers={"Authorization": "Bearer " + token}).status_code == 403, path
            assert client.get(path, headers={"Authorization": "Bearer " + key["key"]}).status_code == 403, path
    finally:
        client.delete(f"/api/v1/users/{created['id']}", headers=auth_headers)
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)


def test_stats_overview_shape_and_pending_counts(client, auth_headers):
    r = client.get("/api/v1/stats/overview", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"resources", "today", "last_7d", "pending", "degraded", "scheduler", "recent_runs"}
    assert set(body["resources"]) >= {"agents", "published_agents", "models", "workflows", "knowledge_bases", "documents", "tools", "prompt_templates", "users", "api_keys", "schedules"}
    assert set(body["pending"]) >= {"awaiting_review", "running", "stuck_running", "failed_today", "failed_documents", "processing_documents", "open_breakers", "unregistered_schedules"}
    assert set(body["today"]) >= {"total", "success", "failed", "total_tokens", "cost", "avg_latency_ms", "success_rate"}
    assert isinstance(body["degraded"], list) and len(body["recent_runs"]) <= 8
    if body["recent_runs"]:
        assert {"agent_name", "workflow_name", "username", "source"} <= set(body["recent_runs"][0])


def test_stats_models_lists_zero_usage_models(client, auth_headers):
    m = client.post("/api/v1/models", headers=auth_headers, json={"name": "pytest-stats-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "http://upstream.test/v1", "api_key": "sk", "model_name": "x", "default_params": {}}).json()
    try:
        r = client.get("/api/v1/stats/models", headers=auth_headers, params={"model_id": m["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["items"] == [{**r.json()["items"][0], "model_id": m["id"], "total": 0, "agents_count": 0, "breaker": None}]
    finally:
        client.delete(f"/api/v1/models/{m['id']}", headers=auth_headers)


def test_stats_workflows_counts_runs_and_last_run(client, auth_headers, workflow):
    _run(client, auth_headers, workflow["id"])
    r = client.get("/api/v1/stats/workflows", headers=auth_headers, params={"workflow_id": workflow["id"], "days": 7})
    item = r.json()["items"][0]
    assert item["workflow_id"] == workflow["id"] and item["total"] >= 1 and item["success"] >= 1
    assert item["last_run_at"] is not None and item["avg_latency_ms"] is not None and item["success_rate"] == 1.0


# ---------- 运行记录：筛选 / 排序 / 区间 / 关联 ----------

def test_runs_list_carries_names_source_and_supports_sort(client, auth_headers, workflow):
    first = _run(client, auth_headers, workflow["id"])
    second = _run(client, auth_headers, workflow["id"])
    r = client.get("/api/v1/runs", headers=auth_headers, params={"workflow_id": workflow["id"], "sort": "started_at", "order": "asc"})
    items = r.json()["items"]
    assert [i["id"] for i in items] == [first["run_id"], second["run_id"]]
    assert items[0]["workflow_name"] == workflow["name"] and items[0]["username"] == "admin" and items[0]["source"] == "ui"
    assert items[0]["run_type"] == "workflow" and items[0]["agent_name"] is None
    bad = client.get("/api/v1/runs", headers=auth_headers, params={"sort": "error"})
    assert bad.status_code == 400 and "不支持的排序字段" in bad.json()["detail"]
    assert client.get("/api/v1/runs", headers=auth_headers, params={"order": "up"}).status_code == 422


def test_runs_time_range_rejects_naive_and_inverted(client, auth_headers):
    naive = client.get("/api/v1/runs", headers=auth_headers, params={"started_from": "2026-09-01T00:00:00"})
    assert naive.status_code == 400 and "时区" in naive.json()["detail"]
    inverted = client.get("/api/v1/runs", headers=auth_headers, params={"started_from": "2026-09-02T00:00:00+08:00", "started_to": "2026-09-01T00:00:00+08:00"})
    assert inverted.status_code == 400 and "早于" in inverted.json()["detail"]


def test_runs_time_range_is_half_open(client, auth_headers, workflow):
    run = _run(client, auth_headers, workflow["id"])
    started = datetime.fromisoformat(client.get(f"/api/v1/runs/{run['run_id']}", headers=auth_headers).json()["started_at"])
    inside = client.get("/api/v1/runs", headers=auth_headers, params={"workflow_id": workflow["id"], "started_from": (started - timedelta(seconds=1)).isoformat(), "started_to": (started + timedelta(seconds=1)).isoformat()})
    assert run["run_id"] in [i["id"] for i in inside.json()["items"]]
    excluded = client.get("/api/v1/runs", headers=auth_headers, params={"workflow_id": workflow["id"], "started_to": started.isoformat()})
    assert run["run_id"] not in [i["id"] for i in excluded.json()["items"]]  # 上界不含


def test_runs_summary_follows_filters_and_reports_latency_distribution(client, auth_headers, workflow):
    _run(client, auth_headers, workflow["id"])
    _run(client, auth_headers, workflow["id"])
    summary = client.get("/api/v1/runs/summary", headers=auth_headers, params={"workflow_id": workflow["id"]}).json()
    listed = client.get("/api/v1/runs", headers=auth_headers, params={"workflow_id": workflow["id"]}).json()
    assert summary["total"] == listed["total"] == summary["success"] == 2
    assert summary["success_rate"] == 1.0 and summary["avg_latency_ms"] is not None and summary["p95_latency_ms"] is not None
    assert sum(b["count"] for b in summary["latency_buckets"]) == 2
    assert [b["label"] for b in summary["latency_buckets"]] == ["<1s", "1-3s", "3-10s", "10-30s", "30-60s", ">60s"]
    assert summary["total_cost"] == 0.0  # workflow 运行没有模型，成本按 0 计但仍计入运行数


def test_run_detail_nodes_have_timestamps_input_output_and_duration(client, auth_headers, workflow):
    run = _run(client, auth_headers, workflow["id"])
    detail = client.get(f"/api/v1/runs/{run['run_id']}", headers=auth_headers).json()
    assert detail["workflow_name"] == workflow["name"] and detail["source"] == "ui"
    nodes = {n["node_id"]: n for n in detail["nodes"]}
    assert set(nodes) == {"s", "c", "e"}
    code_node = nodes["c"]
    assert code_node["started_at"] and code_node["finished_at"] and code_node["duration_ms"] >= 50
    assert code_node["output"] == '"ok"' and code_node["input"] is not None


def test_finalize_run_snapshots_cost_by_model_price(client, auth_headers):
    m = client.post("/api/v1/models", headers=auth_headers, json={"name": "pytest-cost-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "http://upstream.test/v1", "api_key": "sk", "model_name": "x", "default_params": {}, "price_input": 2.0, "price_output": 8.0}).json()
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
    db = SessionLocal()
    try:
        run = run_service.create_run(db, "chat", me, model_id=m["id"], input_data={"message": "hi", "source": "chat"})
        assert run_service.finalize_run(db, run, "success", usage={"prompt_tokens": 1_000_000, "completion_tokens": 500_000, "total_tokens": 1_500_000})
        assert run.cost == 6.0  # 1M × 2 + 0.5M × 8
        # 之后改单价不追溯
        client.put(f"/api/v1/models/{m['id']}", headers=auth_headers, json={"name": m["name"], "provider": "openai", "api_base": "http://upstream.test/v1", "api_key": "", "model_name": "x", "default_params": {}, "price_input": 100.0, "price_output": 100.0})
        detail = client.get(f"/api/v1/runs/{run.id}", headers=auth_headers).json()
        assert detail["cost"] == 6.0 and detail["model_name"] == m["name"] and detail["source"] == "chat"
        no_usage = run_service.create_run(db, "chat", me, model_id=m["id"])
        run_service.finalize_run(db, no_usage, "failed", error="x")
        assert no_usage.cost is None
        for r in (run, no_usage):
            db.delete(r)
        db.commit()
    finally:
        db.close()
        client.delete(f"/api/v1/models/{m['id']}", headers=auth_headers)
