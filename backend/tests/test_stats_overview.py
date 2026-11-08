"""工作台概览：一次请求的查询次数与各计数的口径。

扫描第 15 条：`/stats/overview` 一次请求 ~20 次 DB 往返（12 个资源计数各自一条 + 8 个 pending
+ 两次 period_summary + get_system_status）。合并成一条 UNION ALL 之后，至少把那 12 次压成 1 次。

这个文件的重点是**口径**而非性能数字：概览页上的数字错了没人会报错，只会让人对运营情况判断错。
"""
from __future__ import annotations

import pytest

from app.db.models import Agent, Document, KnowledgeBase, ModelConfig, Run, Tool, User
from app.db.session import SessionLocal
from app.services import stats_service


def test_resource_counts_returns_all_twelve_keys():
    """键集合必须稳定：前端按名字取，少一个就渲染 undefined。"""
    db = SessionLocal()
    try:
        counts = stats_service._resource_counts(db)
    finally:
        db.close()
    assert set(counts) == {
        "agents", "published_agents", "models", "enabled_models", "workflows", "knowledge_bases",
        "documents", "tools", "prompt_templates", "users", "api_keys", "schedules",
    }
    assert all(isinstance(v, int) for v in counts.values())


def test_resource_counts_match_individual_queries():
    """聚合结果必须与逐条查询一致 —— 这是重构后最容易出错的地方（少个 where、写错表名）。"""
    db = SessionLocal()
    try:
        counts = stats_service._resource_counts(db)
        expected = {
            "agents": db.query(Agent).count(),
            "published_agents": db.query(Agent).filter(Agent.status == "published").count(),
            "models": db.query(ModelConfig).count(),
            "enabled_models": db.query(ModelConfig).filter(ModelConfig.is_enabled.is_(True)).count(),
            "documents": db.query(Document).count(),
            "users": db.query(User).filter(User.is_active.is_(True)).count(),
            "tools": db.query(Tool).count(),
        }
    finally:
        db.close()
    for k, v in expected.items():
        assert counts[k] == v, f"{k} 聚合结果 {counts[k]} != 逐条 {v}"


def test_overview_shape_is_stable(client, auth_headers):
    """概览的顶层键要稳定：前端一次性消费这个结构。"""
    res = client.get("/api/v1/stats/overview", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) >= {"resources", "today", "last_7d", "pending", "degraded", "recent_runs"}
    assert isinstance(body["resources"], dict)
    assert isinstance(body["pending"], dict)


def test_pending_has_all_keys(client, auth_headers):
    """pending 的 8 个键一个都不能少（工作台的待处理卡片按名字取）。"""
    res = client.get("/api/v1/stats/overview", headers=auth_headers)
    assert res.status_code == 200
    pending = res.json()["pending"]
    assert set(pending) >= {
        "awaiting_review", "running", "stuck_running", "failed_today",
        "failed_documents", "processing_documents", "open_breakers", "unregistered_schedules",
    }


def test_stuck_running_counts_only_old_running_runs(client, auth_headers):
    """stuck_running 只数「超过 1 小时仍 running」的幽灵记录，刚启动的不算。

    口径写反会让工作台一直报"卡住 N 个"，或永远报 0 —— 两种都不会报错。
    """
    from datetime import datetime, timedelta, timezone

    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.username == "admin").first()
        fresh = Run(run_type="chat", user_id=owner.id, status="running",
                    started_at=datetime.now(timezone.utc), input={}, output={})
        old = Run(run_type="chat", user_id=owner.id, status="running",
                  started_at=datetime.now(timezone.utc) - timedelta(hours=3), input={}, output={})
        done = Run(run_type="chat", user_id=owner.id, status="success",
                   started_at=datetime.now(timezone.utc) - timedelta(hours=3), input={}, output={})
        db.add_all([fresh, old, done])
        db.commit()
        ids = [fresh.id, old.id, done.id]
    finally:
        db.close()

    try:
        body = client.get("/api/v1/stats/overview", headers=auth_headers).json()
        assert body["pending"]["stuck_running"] >= 1, "3 小时前那条应计入"
        assert body["pending"]["running"] >= 2, "刚启动的与 3 小时前的都算 running"
    finally:
        db = SessionLocal()
        try:
            for rid in ids:
                row = db.get(Run, rid)
                if row is not None:
                    db.delete(row)
            db.commit()
        finally:
            db.close()
