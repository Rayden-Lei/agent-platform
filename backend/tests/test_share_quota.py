"""分享链接每日额度：并发不能超扣（2026-11-18）。

修复前 `check_chat_quota` 是"先 count(runs) 再放行"的 check-then-act：
并发请求各自 count 到同一个未超限的数字后全部放行，链接每日总量这个**成本硬上限**直接失效。
现在改成数据库层原子扣减（UPDATE ... WHERE used < limit 按 rowcount 判定）。

并发怎么打：用**多个独立数据库连接 + 多个线程**同时调 `_consume_daily_quota`，
每条连接各自开事务，模拟真实的并发请求（同一个 Session 不能跨线程共用，见 docs/06 第 4 节）。
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.db.models import AgentShare, ShareQuotaUsage
from app.db.session import SessionLocal
from app.services import share_service


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def share_row(client, auth_headers):
    """建一个智能体 + 一条分享（只为拿到一个真实的 agent_shares 行给额度表做外键）。

    不用 public_share 夹具：那会额外打桩模型、发布智能体，本文件只需要一条分享记录。
    """
    made = {"agents": [], "models": []}
    m = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-quota-model-" + _uid(), "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {},
    })
    assert m.status_code == 200, m.text
    made["models"].append(m.json()["id"])
    a = client.post("/api/v1/agents", headers=auth_headers, json={
        "name": "pytest-quota-agent-" + _uid(), "description": "", "system_prompt": "你是助手", "model_id": m.json()["id"], "kb_ids": [],
    })
    assert a.status_code == 200, a.text
    made["agents"].append(a.json()["id"])
    assert client.post(f"/api/v1/agents/{a.json()['id']}/publish", headers=auth_headers).status_code == 200
    r = client.put(f"/api/v1/agents/{a.json()['id']}/share", headers=auth_headers, json={
        "is_enabled": True, "access_mode": "public", "expires_at": None, "rate_limit_per_minute": 20,
        "daily_message_limit": 1000, "visitor_daily_limit": 50, "allow_http_tools": False, "show_citations": True,
    })
    if r.status_code == 409 and client.get(f"/api/v1/agents/{a.json()['id']}", headers=auth_headers).status_code == 404:
        # 并行跑 pytest 的其他会话在 sessionstart / sessionfinish 按 pytest- 前缀全局回收，
        # 把本用例刚建的智能体删掉了，接着建分享就撞外键、被 update_share 的 IntegrityError 兜成 409。
        # 这是共享开发库上多会话并行导致的干扰，不是被测代码的缺陷 —— 明确跳过而不是伪装成失败。
        pytest.skip("智能体在用例执行期间被并行测试会话的全局清理删除，本次结果无效")
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        row = db.query(AgentShare).filter(AgentShare.agent_id == a.json()["id"]).one()
        row_id = row.id
    finally:
        db.close()
    yield row_id
    # 删智能体连带删分享，额度行随 ON DELETE CASCADE 一起清掉
    for aid in made["agents"]:
        client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)
    for mid in made["models"]:
        client.delete(f"/api/v1/models/{mid}", headers=auth_headers)


def _used(share_id: int, visitor_id: str = "") -> int:
    db = SessionLocal()
    try:
        row = db.query(ShareQuotaUsage).filter(
            ShareQuotaUsage.share_id == share_id, ShareQuotaUsage.visitor_id == visitor_id,
        ).one_or_none()
        return row.used if row else 0
    finally:
        db.close()


def _concurrent_consume(share_id: int, limit: int, threads: int, visitor_id: str = "") -> list[bool]:
    """开 threads 条独立连接，同一时刻一起扣减，返回每次是否扣到。"""
    results: list[bool] = []
    external_cleanup: list[str] = []  # 被并行测试会话的全局清理删掉的行（与代码缺陷区分开）
    lock = threading.Lock()
    barrier = threading.Barrier(threads)

    def _worker() -> None:
        db = SessionLocal()
        try:
            barrier.wait()  # 所有线程在这里对齐，尽量同时进临界区
            share = db.get(AgentShare, share_id)
            if share is None:
                with lock:
                    external_cleanup.append(f"分享 {share_id} 已被删除")
                return
            ok = share_service._consume_daily_quota(db, share, visitor_id, limit)
            db.commit()
            with lock:
                results.append(ok)
        except IntegrityError as e:
            db.rollback()
            if "share_quota_usage_share_id_fkey" in str(e) or "agent_shares" in str(e):
                # 并行跑 pytest 的其他会话按 pytest- 前缀全局回收，把夹具造的分享删了，
                # 插入计数行就撞外键。这是共享开发库上多会话并行的干扰，不是被测代码的缺陷。
                with lock:
                    external_cleanup.append(f"分享 {share_id} 在扣减过程中被删除")
                return
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    workers = [threading.Thread(target=_worker) for _ in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join(timeout=60)
        assert not t.is_alive(), "并发扣减线程超时未结束"
    if external_cleanup:
        pytest.skip(f"并行测试会话的全局清理删掉了夹具数据，本次结果无效：{external_cleanup[0]}")
    return results


def test_concurrent_deduction_never_exceeds_limit(share_row):
    """20 个并发请求抢 5 个额度：恰好 5 个成功，计数停在 5，不超扣。"""
    share_id, limit, threads = share_row, 5, 20
    results = _concurrent_consume(share_id, limit, threads)
    succeeded = sum(1 for ok in results if ok)
    assert succeeded == limit, f"应恰好 {limit} 个成功，实际 {succeeded} 个（并发超扣或漏放）"
    assert _used(share_id) == limit, f"计数应停在 {limit}，实际 {_used(share_id)}"


def test_concurrent_deduction_visitor_scope_never_exceeds_limit(share_row):
    """每位访客的每日量同样不能超扣（同一个 visitor_id 并发）。"""
    share_id, limit, threads = share_row, 3, 12
    visitor = "v_" + _uid()
    results = _concurrent_consume(share_id, limit, threads, visitor_id=visitor)
    assert sum(1 for ok in results if ok) == limit
    assert _used(share_id, visitor) == limit


def test_link_and_visitor_counters_are_independent(share_row):
    """链接总量与访客量是两行独立计数，互不串味。"""
    share_id = share_row
    _concurrent_consume(share_id, 100, 1, visitor_id="")
    _concurrent_consume(share_id, 100, 1, visitor_id="v_a")
    _concurrent_consume(share_id, 100, 1, visitor_id="v_b")
    assert _used(share_id) == 1
    assert _used(share_id, "v_a") == 1
    assert _used(share_id, "v_b") == 1


def test_first_deduction_succeeds_when_no_row_exists(share_row):
    """首次对话时计数行还不存在：INSERT ... ON CONFLICT 要建行并扣成功，不能被当成"已达上限"。"""
    assert _used(share_row) == 0
    assert _concurrent_consume(share_row, 1, 1) == [True]
    assert _used(share_row) == 1


def test_zero_remaining_returns_false_without_incrementing(share_row):
    """额度已满时再扣：返回 False 且计数不变（不是先加后判）。"""
    _concurrent_consume(share_row, 1, 1)
    assert _concurrent_consume(share_row, 1, 1) == [False]
    assert _used(share_row) == 1


def test_quota_row_is_unique_per_day_and_visitor(share_row):
    """同一 (分享, 自然日, 访客) 只有一行：并发首次建行靠唯一约束兜住，不产生重复计数行。"""
    for _ in range(5):
        _concurrent_consume(share_row, 100, 1)
    db = SessionLocal()
    try:
        rows = db.query(func.count(ShareQuotaUsage.id)).filter(ShareQuotaUsage.share_id == share_row).scalar()
    finally:
        db.close()
    assert rows == 1, f"同一分享同一天应只有 1 行计数，实际 {rows} 行"


def test_quota_uses_business_timezone_day(share_row):
    """usage_date 按 REPORT_TIMEZONE 切天（与运营统计同口径），不是 UTC 的今天。"""
    from app.config import settings
    from zoneinfo import ZoneInfo

    _concurrent_consume(share_row, 100, 1)
    db = SessionLocal()
    try:
        day = db.query(ShareQuotaUsage.usage_date).filter(ShareQuotaUsage.share_id == share_row).scalar()
    finally:
        db.close()
    expected = share_service._today_start()
    assert day == expected
    # 同时校验它确实是业务时区的零点（避免把 UTC 零点当成业务日）
    assert day.astimezone(ZoneInfo(settings.REPORT_TIMEZONE)).hour == 0
