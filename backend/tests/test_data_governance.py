"""数据治理：定时任务与工作流的写操作要留审计，超期数据要能清理。

2026-11-15 补：schedule_service 与 workflow_service 此前全模块 0 处 record_audit ——
改 cron、删工作流（会级联删掉全部运行记录与会话）都是能造成资金损失或数据丢失的操作，
查不到"谁在什么时候改的"是合规层面的硬伤。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import AuditLog, LlmCall
from app.db.session import SessionLocal
from app.services import retention_service


def _uid() -> str:
    return uuid.uuid4().hex[:6]


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "e"}],
    }


def _audits(client, auth_headers, resource: str, resource_id: int, action: str) -> list:
    r = client.get("/api/v1/audit-logs", headers=auth_headers,
                   params={"resource": resource, "resource_id": resource_id, "action": action, "page_size": 20})
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ===== 定时任务审计 =====

def test_schedule_lifecycle_is_audited(client, auth_headers):
    """建 / 改 / 启停 / 删都要留痕，且改 cron 要记下改前改后。"""
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={
        "name": "pytest-audit-wf-" + _uid(), "description": "", "graph": _graph(),
    })
    assert wf.status_code == 200, wf.text
    wf_id = wf.json()["id"]
    sch = None
    try:
        sch = client.post("/api/v1/schedules", headers=auth_headers, json={
            "name": "pytest-audit-sch-" + _uid(), "workflow_id": wf_id, "cron": "0 3 * * *", "input": {},
        })
        assert sch.status_code == 200, sch.text
        sch_id = sch.json()["id"]

        created = _audits(client, auth_headers, "schedule", sch_id, "create")
        assert len(created) == 1 and created[0]["detail"]["cron"] == "0 3 * * *"

        # 把 cron 改成每分钟：账单会立刻变化，必须看得出改前改后
        upd = client.put(f"/api/v1/schedules/{sch_id}", headers=auth_headers, json={
            "name": "pytest-audit-sch-renamed", "workflow_id": wf_id, "cron": "* * * * *", "input": {},
        })
        assert upd.status_code == 200, upd.text
        updated = _audits(client, auth_headers, "schedule", sch_id, "update")
        assert len(updated) == 1
        assert updated[0]["detail"]["before"]["cron"] == "0 3 * * *"
        assert updated[0]["detail"]["after"]["cron"] == "* * * * *"

        # 停用 / 删除
        assert client.post(f"/api/v1/schedules/{sch_id}/toggle", headers=auth_headers).status_code == 200
        assert len(_audits(client, auth_headers, "schedule", sch_id, "disable")) == 1
        assert client.delete(f"/api/v1/schedules/{sch_id}", headers=auth_headers).status_code == 200
        assert len(_audits(client, auth_headers, "schedule", sch_id, "delete")) == 1
        sch = None
    finally:
        if sch is not None:
            client.delete(f"/api/v1/schedules/{sch['id']}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wf_id}", headers=auth_headers)


def test_schedule_unchanged_toggle_does_not_duplicate_audit(client, auth_headers):
    """状态没变化时不该留第二条第记录（开关点两次、或并发重复提交）。"""
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={
        "name": "pytest-audit-wf2-" + _uid(), "description": "", "graph": _graph(),
    }).json()
    sch = client.post("/api/v1/schedules", headers=auth_headers, json={
        "name": "pytest-audit-sch2-" + _uid(), "workflow_id": wf["id"], "cron": "0 3 * * *", "input": {},
    }).json()
    try:
        client.post(f"/api/v1/schedules/{sch['id']}/toggle", headers=auth_headers)  # 停用
        client.post(f"/api/v1/schedules/{sch['id']}/toggle", headers=auth_headers)  # 启用
        client.post(f"/api/v1/schedules/{sch['id']}/toggle", headers=auth_headers)  # 又停用
        assert len(_audits(client, auth_headers, "schedule", sch["id"], "disable")) == 2
        assert len(_audits(client, auth_headers, "schedule", sch["id"], "enable")) == 1
    finally:
        client.delete(f"/api/v1/schedules/{sch['id']}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)


# ===== 工作流审计 =====

def test_workflow_lifecycle_is_audited(client, auth_headers):
    """建 / 改 / 删都要留痕。删除会级联删掉运行记录与会话，最不该无声发生。"""
    name = "pytest-wf-audit-" + _uid()
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": name, "description": "", "graph": _graph()})
    assert wf.status_code == 200, wf.text
    wf_id = wf.json()["id"]

    assert [a["detail"]["name"] for a in _audits(client, auth_headers, "workflow", wf_id, "create")] == [name]

    upd = client.put(f"/api/v1/workflows/{wf_id}", headers=auth_headers, json={
        "name": name + "-v2", "description": "", "graph": _graph(),
    })
    assert upd.status_code == 200, upd.text
    updated = _audits(client, auth_headers, "workflow", wf_id, "update")
    assert len(updated) == 1 and updated[0]["detail"]["version"] == upd.json()["version"]

    assert client.delete(f"/api/v1/workflows/{wf_id}", headers=auth_headers).status_code == 200
    assert [a["detail"]["name"] for a in _audits(client, auth_headers, "workflow", wf_id, "delete")] == [name + "-v2"]


# ===== 数据保留 =====

def test_retention_skips_when_disabled(monkeypatch):
    """关掉开关时任务必须直接返回，不能误删。"""
    from app.config import settings

    monkeypatch.setattr(settings, "DATA_RETENTION_ENABLED", False)
    assert retention_service.purge_expired() == {}


def test_retention_removes_only_rows_past_cutoff(monkeypatch):
    """只删超期行：新行必须留着（按时间窗删，不按行数）。"""
    from app.config import settings

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    ids = []
    try:
        # 字段按 LlmCall 的实际定义（model_name / url，没有 provider / api_base）
        fresh = LlmCall(
            purpose="chat", model_name="pytest-model", url="http://x/v1",
            status="success", started_at=now - timedelta(days=1),
        )
        stale = LlmCall(
            purpose="chat", model_name="pytest-model", url="http://x/v1",
            status="success", started_at=now - timedelta(days=settings.LLM_LOG_RETENTION_DAYS + 5),
        )
        db.add_all([fresh, stale])
        db.commit()
        fresh_id, stale_id = fresh.id, stale.id
        ids = [fresh_id, stale_id]
    finally:
        db.close()

    try:
        deleted = retention_service.purge_expired()
        assert deleted.get("llm_calls", 0) >= 1

        db = SessionLocal()
        try:
            assert db.get(LlmCall, stale_id) is None, "超期行必须删掉"
            assert db.get(LlmCall, fresh_id) is not None, "未超期行必须保留"
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            for rid in ids:
                row = db.get(LlmCall, rid)
                if row is not None:
                    db.delete(row)
            db.commit()
        finally:
            db.close()


def test_retention_is_registered_in_scheduler():
    """清理任务要真的挂上调度器，否则配置文件写了也不会执行。"""
    from app.core import scheduler as scheduler_mod

    sched = scheduler_mod.get_scheduler()
    job = sched.get_job(scheduler_mod.RETENTION_JOB_ID)
    assert job is not None, "数据保留任务未注册到调度器"
    assert job.trigger is not None
