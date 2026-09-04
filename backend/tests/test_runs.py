"""运行记录收尾回归用例。

覆盖历史缺陷：started_at/finished_at/latency_ms 从未写入；定时任务未传 thread_id 抛错后被吞、
运行永远 running；对话被客户端中断后运行永远 running。
"""
import pytest

from app.core.scheduler import _run_scheduled_job
from app.db.models import Conversation, Message, Run
from app.db.session import SessionLocal
from app.services import chat_service, run_service

START_END_GRAPH = {
    "nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "e", "type": "end", "config": {}}],
    "edges": [{"from": "s", "to": "e"}],
}

# code 节点主动抛异常，用来验证失败路径同样能收尾
FAILING_GRAPH = {
    "nodes": [
        {"id": "s", "type": "start", "config": {}},
        {"id": "boom", "type": "code", "config": {"code": "raise ValueError('boom-from-pytest')"}},
        {"id": "e", "type": "end", "config": {}},
    ],
    "edges": [{"from": "s", "to": "boom"}, {"from": "boom", "to": "e"}],
}

# 每年 1 月 1 日 0 点，测试过程中不会被调度器真的触发
NEVER_SOON_CRON = "0 0 1 1 *"


def _create_workflow(client, auth_headers, graph, name):
    res = client.post("/api/v1/workflows", headers=auth_headers, json={"name": name, "description": "", "graph": graph})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _create_schedule(client, auth_headers, wid, name):
    res = client.post("/api/v1/schedules", headers=auth_headers, json={
        "name": name, "workflow_id": wid, "cron": NEVER_SOON_CRON, "input": {"input": "x"},
    })
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _runs_of_workflow(client, auth_headers, wid):
    return [r for r in client.get("/api/v1/runs", headers=auth_headers).json() if r["workflow_id"] == wid]


def test_workflow_run_success_writes_timing(client, auth_headers):
    wid = _create_workflow(client, auth_headers, START_END_GRAPH, "pytest-run-timing")
    try:
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"input": "hello"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "success"

        detail = client.get(f"/api/v1/runs/{r.json()['run_id']}", headers=auth_headers).json()
        assert detail["status"] == "success"
        assert detail["started_at"] is not None
        assert detail["finished_at"] is not None
        assert detail["finished_at"] >= detail["started_at"]
        assert detail["latency_ms"] >= 0
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_workflow_run_failure_is_finalized(client, auth_headers):
    wid = _create_workflow(client, auth_headers, FAILING_GRAPH, "pytest-run-failure")
    try:
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"input": "hello"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"
        assert "boom-from-pytest" in r.json()["error"]

        detail = client.get(f"/api/v1/runs/{r.json()['run_id']}", headers=auth_headers).json()
        assert detail["status"] == "failed"
        assert "boom-from-pytest" in detail["error"]
        assert detail["finished_at"] is not None
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_scheduled_job_run_is_finalized(client, auth_headers):
    wid = _create_workflow(client, auth_headers, START_END_GRAPH, "pytest-sched-ok")
    sid = None
    try:
        sid = _create_schedule(client, auth_headers, wid, "pytest-sched-ok")
        _run_scheduled_job(sid)

        runs = _runs_of_workflow(client, auth_headers, wid)
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["finished_at"] is not None

        sched = next(s for s in client.get("/api/v1/schedules", headers=auth_headers).json() if s["id"] == sid)
        assert sched["last_run_at"] is not None
    finally:
        if sid:
            client.delete(f"/api/v1/schedules/{sid}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_scheduled_job_failure_marks_run_failed(client, auth_headers):
    wid = _create_workflow(client, auth_headers, FAILING_GRAPH, "pytest-sched-fail")
    sid = None
    try:
        sid = _create_schedule(client, auth_headers, wid, "pytest-sched-fail")
        _run_scheduled_job(sid)  # 不得抛出：异常要落到 run.error 而不是冒泡到调度器

        runs = _runs_of_workflow(client, auth_headers, wid)
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        assert "boom-from-pytest" in runs[0]["error"]
        assert runs[0]["finished_at"] is not None

        sched = next(s for s in client.get("/api/v1/schedules", headers=auth_headers).json() if s["id"] == sid)
        assert sched["last_run_at"] is not None
    finally:
        if sid:
            client.delete(f"/api/v1/schedules/{sid}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_scheduled_job_disabled_is_skipped(client, auth_headers):
    wid = _create_workflow(client, auth_headers, START_END_GRAPH, "pytest-sched-disabled")
    sid = None
    try:
        sid = _create_schedule(client, auth_headers, wid, "pytest-sched-disabled")
        t = client.post(f"/api/v1/schedules/{sid}/toggle", headers=auth_headers)
        assert t.status_code == 200 and t.json()["is_enabled"] is False

        _run_scheduled_job(sid)
        assert _runs_of_workflow(client, auth_headers, wid) == []
    finally:
        if sid:
            client.delete(f"/api/v1/schedules/{sid}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_finalize_run_is_idempotent_and_rejects_non_final(client, auth_headers):
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()
    db = SessionLocal()
    run = None
    try:
        run = run_service.create_run(db, "workflow", me["id"], input_data={"input": "pytest"})
        assert run.started_at is not None

        assert run_service.finalize_run(db, run, "success", output={"output": 1}) is True
        assert run.finished_at is not None and run.latency_ms >= 0

        # 二次收尾不得覆盖首次结果
        assert run_service.finalize_run(db, run, "failed", error="late") is False
        db.refresh(run)
        assert run.status == "success" and run.error is None

        with pytest.raises(ValueError):
            run_service.finalize_run(db, run, "awaiting_review")
    finally:
        if run is not None:
            db.delete(run)
            db.commit()
        db.close()


def test_chat_cancel_finalizes_run_once(client, auth_headers):
    """客户端中断：部分回答落库、运行置为 cancelled；重复收尾不重复写消息。"""
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()
    db = SessionLocal()
    conv = None
    run = None
    try:
        conv = Conversation(user_id=me["id"], title="pytest-cancel")
        db.add(conv)
        db.commit()
        db.refresh(conv)
        run = run_service.create_run(db, "chat", me["id"], input_data={"message": "hi"})

        assert chat_service.finalize_cancelled_chat(db, run.id, conv.id, "部分回答", [], {}, []) is True
        db.refresh(run)
        assert run.status == "cancelled"
        assert run.output == {"content": "部分回答"}
        assert run.finished_at is not None

        assert chat_service.finalize_cancelled_chat(db, run.id, conv.id, "部分回答", [], {}, []) is False
        msgs = db.query(Message).filter(Message.conversation_id == conv.id).all()
        assert [m.content for m in msgs] == ["部分回答"]
    finally:
        if run is not None:
            db.delete(run)
        if conv is not None:
            db.delete(conv)  # messages 由外键 CASCADE 级联删除
        db.commit()
        db.close()
