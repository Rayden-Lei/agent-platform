"""运行记录来源列（docs/15 OP-09a）与 M1 迁移的数据逻辑（来源回填、已发布智能体补发）。

迁移函数都带 ID 范围参数：用例只动自己造的数据，不碰共享库里的真实智能体与运行记录。
"""
import importlib.util
import json
import pathlib
import uuid

import pytest
from sqlalchemy import text

from app.db.models import Agent, Run
from app.db.session import SessionLocal, engine
from app.runtime.agent_config import snapshot_of
from app.services import run_service

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrations" / "20260925_171639_f9uow2_agent_publish_and_run_source.py"
START_END = {"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "e", "type": "end", "config": {}}], "edges": [{"from": "s", "to": "e"}]}


def _script():
    spec = importlib.util.spec_from_file_location("m1_agent_publish_and_run_source", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _me(client, auth_headers) -> int:
    return client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]


def test_create_run_rejects_unknown_source(client, auth_headers):
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="运行来源"):
            run_service.create_run(db, "chat", _me(client, auth_headers), source="share-link")
    finally:
        db.close()


def test_workflow_run_records_ui_and_api_key_sources(client, auth_headers):
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-source-wf", "description": "", "graph": START_END}).json()
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-source-key", "quota": 5, "workflow_ids": [wf["id"]]}).json()
    try:
        by_ui = client.post(f"/api/v1/workflows/{wf['id']}/run", headers=auth_headers, json={"input": "x"}).json()
        by_key = client.post(f"/api/v1/workflows/{wf['id']}/run", headers={"Authorization": "Bearer " + key["key"]}, json={"input": "x"}).json()
        ui_run = client.get(f"/api/v1/runs/{by_ui['run_id']}", headers=auth_headers).json()
        key_run = client.get(f"/api/v1/runs/{by_key['run_id']}", headers=auth_headers).json()
        assert (ui_run["source"], ui_run["api_key_id"]) == ("ui", None)
        assert (key_run["source"], key_run["api_key_id"], key_run["schedule_id"]) == ("api_key", key["id"], None)
        db = SessionLocal()
        try:
            assert db.get(Run, by_key["run_id"]).input == {"input": "x"}  # 来源只在列里，input 只放业务输入
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)


def test_source_filter_uses_column(client, auth_headers):
    me = _me(client, auth_headers)
    db = SessionLocal()
    runs = []
    try:
        for source in ("chat", "debug", "share"):
            runs.append(run_service.create_run(db, "chat", me, input_data={"message": "pytest-source"}, source=source))
        chat_id, debug_id, share_id = runs[0].id, runs[1].id, runs[2].id
        debug_ids = {r["id"] for r in client.get("/api/v1/runs", headers=auth_headers, params={"source": "debug", "page_size": 100}).json()["items"]}
        chat_ids = {r["id"] for r in client.get("/api/v1/runs", headers=auth_headers, params={"source": "chat", "page_size": 100}).json()["items"]}
        share_ids = {r["id"] for r in client.get("/api/v1/runs", headers=auth_headers, params={"source": "share", "page_size": 100}).json()["items"]}
        assert debug_id in debug_ids and chat_id not in debug_ids
        assert chat_id in chat_ids
        assert share_id in share_ids and chat_id not in share_ids  # share 是分享访客的来源（2026-10-05 PB-01 起合法）
        assert client.get("/api/v1/runs", headers=auth_headers, params={"source": "guest"}).status_code == 422
    finally:
        for r in runs:
            db.delete(r)
        db.commit()
        db.close()


def test_m1_backfills_legacy_sources_only_where_derivable(client, auth_headers):
    """旧代码写入的行：列是默认 ui、来源在 input 里 —— 按 input 推算改写；新代码显式写的不动；第二次执行 0 行。"""
    script = _script()
    me = _me(client, auth_headers)
    ids: list[int] = []
    with engine.begin() as conn:
        for run_type, payload in (("chat", {"message": "hi"}), ("workflow", {"scheduled": True, "input": ""}), ("workflow", {"source": "api_key", "input": ""}), ("workflow", {"input": ""})):
            ids.append(conn.execute(
                text("INSERT INTO runs (run_type, user_id, status, input, output, token_usage, latency_ms) VALUES (:t, :u, 'success', CAST(:i AS jsonb), '{}', '{}', 0) RETURNING id"),
                {"t": run_type, "u": me, "i": json.dumps(payload)},
            ).scalar())
        # 新代码显式写入 debug：推算值是 chat，但不能被改写
        ids.append(conn.execute(text("INSERT INTO runs (run_type, user_id, status, input, output, token_usage, latency_ms, source) VALUES ('chat', :u, 'success', '{}', '{}', '{}', 0, 'debug') RETURNING id"), {"u": me}).scalar())
    try:
        with engine.begin() as conn:
            assert script.backfill_sources(conn, ids) == 3
            assert script.backfill_sources(conn, ids) == 0
        db = SessionLocal()
        try:
            got = [db.get(Run, i).source for i in ids]
        finally:
            db.close()
        assert got == ["chat", "schedule", "api_key", "ui", "debug"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM runs WHERE id = ANY(:ids)"), {"ids": ids})


def test_m1_points_unchanged_published_agent_and_republishes_changed_one(client, auth_headers):
    """迁移前的发布态：status=published、没有线上指针。与最新快照一致 → 指向它；改过 → 按当前行补发，线上行为不变。"""
    script = _script()
    model = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-m1-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "http://upstream.test/v1", "api_key": "sk-test", "model_name": "x", "default_params": {},
    }).json()
    agents = [client.post("/api/v1/agents", headers=auth_headers, json={
        "name": f"pytest-m1-{suffix}-" + uuid.uuid4().hex[:6], "description": "", "system_prompt": "原提示词", "model_id": model["id"],
    }).json() for suffix in ("same", "changed")]
    same, changed = agents[0]["id"], agents[1]["id"]
    try:
        db = SessionLocal()
        try:
            snapshots = {aid: snapshot_of(db.get(Agent, aid)) for aid in (same, changed)}
        finally:
            db.close()
        with engine.begin() as conn:
            for aid in (same, changed):
                conn.execute(text("UPDATE agents SET status = 'published', version = 2, published_version = NULL WHERE id = :a"), {"a": aid})
                conn.execute(text("INSERT INTO agent_versions (agent_id, version, snapshot) VALUES (:a, 2, CAST(:s AS jsonb))"), {"a": aid, "s": json.dumps(snapshots[aid])})
            conn.execute(text("UPDATE agents SET system_prompt = '发布后又改过' WHERE id = :a"), {"a": changed})
        with engine.begin() as conn:
            plans = {p["agent_id"]: p for p in script.plan_republish(conn, [same, changed])}
            assert (plans[same]["action"], plans[same]["version"]) == ("point", 2)
            assert (plans[changed]["action"], plans[changed]["version"]) == ("republish", 3)
            script.apply_republish(conn, list(plans.values()))
        with engine.begin() as conn:
            rows = {r["id"]: r for r in conn.execute(text("SELECT id, version, published_version FROM agents WHERE id IN (:a, :b)"), {"a": same, "b": changed}).mappings()}
            assert rows[same]["published_version"] == 2 and rows[changed]["published_version"] == 3 and rows[changed]["version"] == 3
            v3 = conn.execute(text("SELECT snapshot, note FROM agent_versions WHERE agent_id = :a AND version = 3"), {"a": changed}).mappings().one()
            assert v3["snapshot"]["system_prompt"] == "发布后又改过" and v3["note"] == "迁移补发"
            assert script.plan_republish(conn, [same, changed]) == []  # 已有指针的不再处理
    finally:
        for aid in (same, changed):
            client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)
        client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)
