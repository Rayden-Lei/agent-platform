"""卡住运行的处置与检查点回收（docs/15 OP-10、WF-12）。

为什么单独一个文件：这两条链路的失败都不会报错 ——
- 没有处置入口时，进程被杀留下的 status=running 会永久占着"运行中"，工作台一直报"卡住 N 个"，
  而运行记录页没有任何终止入口，只能连库改数据（docs/15 记录过共享库长期挂着一条超过 1 小时的 running）；
- 检查点永不回收时，checkpoints / checkpoint_blobs / checkpoint_writes 三张表只涨不消，最终撑爆磁盘。
两者都不会抛异常，只能靠断言"状态变没变""库里的行在不在"。

覆盖：
1. 单条处置：未超阈值 400、已终态 409、不存在 404、越权 403、超阈值成功且检查点被删、写审计；
2. 批量处置：部分失败时逐条返回成功 / 失败清单，成功的那些检查点确实被删；
3. 保留期清理：终态运行的残留检查点被回收、running 与未超期的 awaiting_review 不动、
   超期 awaiting_review 先收尾成 failed 再删检查点。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from psycopg import connect
from psycopg.rows import dict_row

from app.config import settings
from app.db.models import Run, User
from app.db.session import SessionLocal
from app.services import retention_service, run_service
from app.workflow.checkpointer import libpq_dsn, new_saver

TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


def checkpoint_rows(thread_id: str) -> dict[str, int]:
    """某个 thread 在三张检查点表里的行数（与 tests/test_checkpoint_cleanup.py 同一口径）。"""
    with connect(libpq_dsn(settings.DATABASE_URL), autocommit=True, row_factory=dict_row) as conn:
        return {t: conn.execute(f"SELECT count(*) AS n FROM {t} WHERE thread_id = %s", (thread_id,)).fetchone()["n"]
                for t in TABLES}


def _seed_checkpoints(thread_id: str) -> None:
    """直接往 thread 里写一份检查点，不跑图。

    为什么不用真跑图造数据：本文件要验证的是"清理逻辑删不删"，与图的执行语义无关；
    真跑一条工作流要起线程池、写 run_nodes，既慢又会给共享库留垃圾。这里用 saver 的公开接口
    put 写一条最小 state，效果与跑完一个节点一样 —— 三张表都有行。
    """
    saver = new_saver()
    saver.put(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        {"v": 1, "id": "cp-" + uuid.uuid4().hex[:8], "ts": datetime.now(timezone.utc).isoformat(),
         "channel_values": {}, "channel_versions": {}, "versions_seen": {}, "updated_channels": None},
        {"source": "input", "step": 0, "parents": {}},
        {},
    )


def _make_run(db, *, status: str, started_at: datetime | None, run_type: str = "workflow") -> Run:
    """直接造一条指定状态与发起时间的运行记录（绕过 create_run，因为要造"超期仍 running"这种状态）。

    生产代码禁止这么造（05 铁律 4），测试里必须 —— create_run 只会写 running + 当前时间。
    """
    owner = db.query(User).filter(User.username == "admin").first()
    run = Run(run_type=run_type, user_id=owner.id, status=status, started_at=started_at,
              input={}, output={}, source="ui")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _drop(db, run: Run | None) -> None:
    """收尾清理：按"建成功了才删"各自判断，不依赖前一步的返回值（05 第 6 节）。"""
    if run is None:
        return
    row = db.get(Run, run.id)
    if row is not None:
        db.delete(row)
        db.commit()


def _audits(client, auth_headers, run_id: int, action: str) -> list:
    r = client.get("/api/v1/audit-logs", headers=auth_headers,
                   params={"resource": "run", "resource_id": run_id, "action": action, "page_size": 20})
    assert r.status_code == 200, r.text
    return r.json()["items"]


# --------------------------------------------------------------- 1. 单条处置

def test_mark_stuck_run_failed_deletes_checkpoints_and_audits(client, auth_headers):
    """超阈值的 running 被置为 failed：状态、原因、finished_at、检查点、审计五样都要对。"""
    db = SessionLocal()
    run = None
    thread_id = None
    try:
        run = _make_run(db, status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=settings.STUCK_RUN_MINUTES + 5))
        thread_id = str(run.id)
        _seed_checkpoints(thread_id)
        assert checkpoint_rows(thread_id)["checkpoints"] >= 1, "前置条件：检查点必须真的写进去了"
        run_id = run.id
    finally:
        db.close()

    try:
        res = client.post(f"/api/v1/runs/{run_id}/mark-failed", headers=auth_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "failed"
        assert body["error"] == run_service.STUCK_RUN_REASON
        assert body["finished_at"] is not None, "处置必须经 finalize_run 收尾，否则耗时统计里既不在 running 也不在已结束"

        detail = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers).json()
        assert detail["status"] == "failed"
        assert detail["latency_ms"] >= 0

        # 检查点必须真的被删（这是本接口存在的另一半理由）
        assert checkpoint_rows(thread_id) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}

        audits = _audits(client, auth_headers, run_id, "mark_failed")
        assert len(audits) == 1, "人工终止运行必须留审计"
        assert audits[0]["detail"]["reason"] == run_service.STUCK_RUN_REASON
        assert audits[0]["detail"]["previous_status"] == "running"
    finally:
        db = SessionLocal()
        try:
            _drop(db, run)
        finally:
            db.close()


def test_mark_failed_rejects_run_within_threshold(client, auth_headers):
    """未超阈值的 running 必须 400：接口只改数据库状态、不会中断仍在执行的线程，提前放行等于篡改结果。"""
    db = SessionLocal()
    run = None
    try:
        run = _make_run(db, status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        run_id = run.id
    finally:
        db.close()

    try:
        res = client.post(f"/api/v1/runs/{run_id}/mark-failed", headers=auth_headers)
        assert res.status_code == 400, res.text
        assert str(settings.STUCK_RUN_MINUTES) in res.json()["detail"]

        db = SessionLocal()
        try:
            row = db.get(Run, run_id)
            assert row.status == "running", "被拒绝的请求不能改状态"
            assert row.finished_at is None
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            _drop(db, run)
        finally:
            db.close()


def test_mark_failed_rejects_final_status(client, auth_headers):
    """已终态的运行 409：不能用处置入口把 success 改写成 failed。"""
    db = SessionLocal()
    run = None
    try:
        run = _make_run(db, status="success", started_at=datetime.now(timezone.utc) - timedelta(hours=5))
        run_id = run.id
    finally:
        db.close()

    try:
        res = client.post(f"/api/v1/runs/{run_id}/mark-failed", headers=auth_headers)
        assert res.status_code == 409, res.text
        assert "success" in res.json()["detail"]

        db = SessionLocal()
        try:
            assert db.get(Run, run_id).status == "success", "409 之后状态必须原样不动"
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            _drop(db, run)
        finally:
            db.close()


def test_mark_failed_unknown_run_is_404(client, auth_headers):
    """不存在的运行 404，不能 500。"""
    res = client.post("/api/v1/runs/99999999/mark-failed", headers=auth_headers)
    assert res.status_code == 404, res.text


def test_mark_failed_requires_admin_or_developer(client, auth_headers, caller_headers):
    """越权：caller 调处置接口 403，且状态不变。"""
    db = SessionLocal()
    run = None
    try:
        run = _make_run(db, status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=settings.STUCK_RUN_MINUTES + 5))
        run_id = run.id
    finally:
        db.close()

    try:
        res = client.post(f"/api/v1/runs/{run_id}/mark-failed", headers=caller_headers)
        assert res.status_code == 403, res.text

        db = SessionLocal()
        try:
            assert db.get(Run, run_id).status == "running", "越权请求不能改状态"
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            _drop(db, run)
        finally:
            db.close()


# --------------------------------------------------------------- 2. 批量处置

def test_batch_mark_failed_returns_per_item_result(client, auth_headers):
    """批量：一条合格 + 一条未超阈值 + 一条已终态 → 成功的进 succeeded 且检查点被删，其余进 failed。"""
    db = SessionLocal()
    runs: list[Run] = []
    try:
        ok_run = _make_run(db, status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=settings.STUCK_RUN_MINUTES + 5))
        _seed_checkpoints(str(ok_run.id))
        fresh = _make_run(db, status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        done = _make_run(db, status="success", started_at=datetime.now(timezone.utc) - timedelta(hours=5))
        runs = [ok_run, fresh, done]
        ids = {"ok": ok_run.id, "fresh": fresh.id, "done": done.id}
    finally:
        db.close()

    try:
        res = client.post("/api/v1/runs/batch", headers=auth_headers,
                          json={"ids": list(ids.values()), "action": "mark_failed"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["succeeded"] == [ids["ok"]], body
        failed = {item["id"]: item["detail"] for item in body["failed"]}
        assert set(failed) == {ids["fresh"], ids["done"]}
        assert str(settings.STUCK_RUN_MINUTES) in failed[ids["fresh"]]
        assert "success" in failed[ids["done"]]

        # 成功那条的检查点必须真的被删；被拒的两条状态不变
        assert checkpoint_rows(str(ids["ok"])) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}
        db = SessionLocal()
        try:
            assert db.get(Run, ids["fresh"]).status == "running"
            assert db.get(Run, ids["done"]).status == "success"
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            for run in runs:
                _drop(db, run)
        finally:
            db.close()


def test_batch_mark_failed_rejects_unknown_action(client, auth_headers):
    """action 只接受 mark_failed，别的取值 422（路由用 Literal 收窄）。"""
    res = client.post("/api/v1/runs/batch", headers=auth_headers, json={"ids": [1], "action": "delete"})
    assert res.status_code == 422, res.text


# --------------------------------------------------------------- 3. stuck 筛选

def test_list_runs_stuck_filter(client, auth_headers):
    """?stuck=true 只列出超阈值仍 running 的；刚起的 running 与已终态都不出现。"""
    db = SessionLocal()
    runs: list[Run] = []
    try:
        old = _make_run(db, status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=settings.STUCK_RUN_MINUTES + 30))
        fresh = _make_run(db, status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        done = _make_run(db, status="failed", started_at=datetime.now(timezone.utc) - timedelta(minutes=settings.STUCK_RUN_MINUTES + 30))
        runs = [old, fresh, done]
        ids = [old.id, fresh.id, done.id]
    finally:
        db.close()

    try:
        items = client.get("/api/v1/runs", headers=auth_headers, params={"stuck": "true", "page_size": 100}).json()["items"]
        got = {item["id"] for item in items}
        assert ids[0] in got, "超阈值仍 running 的必须被列出"
        assert ids[1] not in got, "刚起的 running 不算卡住"
        assert ids[2] not in got, "已终态的不算卡住"
        assert all(item["status"] == "running" for item in items if item["id"] in ids)
    finally:
        db = SessionLocal()
        try:
            for run in runs:
                _drop(db, run)
        finally:
            db.close()


# --------------------------------------------------------------- 4. 保留期清理检查点

def test_retention_purges_terminal_run_checkpoints(client, auth_headers):
    """终态运行的残留检查点被回收；仍在 running 的绝不碰。"""
    db = SessionLocal()
    runs: list[Run] = []
    try:
        grace = timedelta(hours=settings.CHECKPOINT_TERMINAL_GRACE_HOURS + 1)
        finished = _make_run(db, status="success", started_at=datetime.now(timezone.utc) - grace)
        alive = _make_run(db, status="running", started_at=datetime.now(timezone.utc) - grace)
        _seed_checkpoints(str(finished.id))
        _seed_checkpoints(str(alive.id))
        runs = [finished, alive]
        finished_id, alive_id = finished.id, alive.id
    finally:
        db.close()

    try:
        assert checkpoint_rows(str(finished_id))["checkpoints"] >= 1
        assert checkpoint_rows(str(alive_id))["checkpoints"] >= 1

        deleted = retention_service.purge_expired()
        assert deleted.get("workflow_checkpoints", 0) >= 1, deleted

        assert checkpoint_rows(str(finished_id)) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}, \
            "终态运行的残留检查点必须回收"
        assert checkpoint_rows(str(alive_id))["checkpoints"] >= 1, "仍在 running 的检查点绝不能删（执行线程还在写）"
    finally:
        db = SessionLocal()
        try:
            for run in runs:
                _drop(db, run)
        finally:
            db.close()


def test_retention_keeps_recent_awaiting_review_checkpoints(client, auth_headers):
    """未超期的 awaiting_review 检查点必须留着：resume 靠它找回被 interrupt 的图。"""
    db = SessionLocal()
    run = None
    try:
        run = _make_run(db, status="awaiting_review", started_at=datetime.now(timezone.utc) - timedelta(days=1))
        _seed_checkpoints(str(run.id))
        run_id = run.id
    finally:
        db.close()

    try:
        retention_service.purge_expired()
        assert checkpoint_rows(str(run_id))["checkpoints"] >= 1, "未超期的待审核检查点是续跑依据，不能清"

        db = SessionLocal()
        try:
            row = db.get(Run, run_id)
            assert row.status == "awaiting_review", "未超期的待审核运行不该被收尾"
            assert row.finished_at is None
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            _drop(db, run)
        finally:
            db.close()


def test_retention_expires_stale_awaiting_review(client, auth_headers):
    """超期未审批的 awaiting_review：先收尾成 failed，再删检查点。

    顺序不能反：只删检查点不收尾的话，这条运行会永远停在 awaiting_review，
    审批一提交就从空 state 重跑（用户以为审批生效了其实没有）。
    """
    db = SessionLocal()
    run = None
    try:
        days = settings.CHECKPOINT_AWAITING_REVIEW_RETENTION_DAYS + 1
        run = _make_run(db, status="awaiting_review", started_at=datetime.now(timezone.utc) - timedelta(days=days))
        _seed_checkpoints(str(run.id))
        run_id = run.id
    finally:
        db.close()

    try:
        deleted = retention_service.purge_expired()
        assert deleted.get("expired_awaiting_review", 0) >= 1, deleted
        assert checkpoint_rows(str(run_id)) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}

        db = SessionLocal()
        try:
            row = db.get(Run, run_id)
            assert row.status == "failed", "超期未审批的运行必须一并收尾，否则会永远停在待审核"
            assert row.error == retention_service.AWAITING_REVIEW_EXPIRED_REASON
            assert row.finished_at is not None
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            _drop(db, run)
        finally:
            db.close()


def test_retention_skips_all_checkpoint_purge_when_disabled(monkeypatch, client, auth_headers):
    """DATA_RETENTION_ENABLED=false 时连检查点也不清（开关必须管住全部清理动作）。"""
    db = SessionLocal()
    run = None
    try:
        grace = timedelta(hours=settings.CHECKPOINT_TERMINAL_GRACE_HOURS + 1)
        run = _make_run(db, status="failed", started_at=datetime.now(timezone.utc) - grace)
        _seed_checkpoints(str(run.id))
        run_id = run.id
    finally:
        db.close()

    try:
        monkeypatch.setattr(settings, "DATA_RETENTION_ENABLED", False)
        assert retention_service.purge_expired() == {}
        assert checkpoint_rows(str(run_id))["checkpoints"] >= 1, "开关关闭时不能删任何东西"
    finally:
        db = SessionLocal()
        try:
            _drop(db, run)
        finally:
            db.close()


def test_retention_purges_orphan_test_run_thread(client, auth_headers):
    """thread_id 不是运行记录 id 的（编辑器试运行的 test-<uuid>）也要能回收。

    这类 thread 没有任何业务状态依赖它，留着就是纯垃圾。
    """
    thread_id = "test-" + uuid.uuid4().hex[:12]
    _seed_checkpoints(thread_id)
    try:
        assert checkpoint_rows(thread_id)["checkpoints"] >= 1
        deleted = retention_service.purge_expired()
        assert deleted.get("workflow_checkpoints", 0) >= 1, deleted
        assert checkpoint_rows(thread_id) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}
    finally:
        # 兜底：用例失败时别把 thread 留在库里
        from app.workflow.checkpointer import delete_thread_safely
        delete_thread_safely(thread_id)


# --------------------------------------------------------------- 5. 待审批的运行不能被处置

def test_mark_failed_rejects_awaiting_review_run(client, auth_headers):
    """awaiting_review 的运行**不能**被处置入口改掉：它不是 running。

    这条用例钉住"别把待审批的运行当成卡住的运行处置" —— 它看起来"没在动"
    （没有 finished_at、很久不更新），但检查点是审批后 resume 的唯一依据，删了就续不上。

    为什么直接造数而不真跑一条工作流到人工审核节点：真跑出来的运行记录名字带 pytest- 前缀、
    挂在 pytest- 工作流下，并行跑测试时会被别的会话的 pytest_sessionstart 按前缀回收掉，
    用例就变成"看别人什么时候开跑"的随机失败。这里造数 + 手动写一份检查点，
    验证的仍是同一条业务规则，且完全自包含。真实跑图到 awaiting_review 的路径
    由 tests/test_checkpoint_cleanup.py 覆盖（那里断言检查点必须留着）。
    """
    db = SessionLocal()
    run = None
    thread_id = None
    try:
        run = _make_run(db, status="awaiting_review", started_at=datetime.now(timezone.utc) - timedelta(hours=3))
        thread_id = str(run.id)
        _seed_checkpoints(thread_id)
        run_id = run.id
        assert checkpoint_rows(thread_id)["checkpoints"] >= 1
    finally:
        db.close()

    try:
        res = client.post(f"/api/v1/runs/{run_id}/mark-failed", headers=auth_headers)
        assert res.status_code == 409, res.text
        assert "awaiting_review" in res.json()["detail"]

        assert checkpoint_rows(thread_id)["checkpoints"] >= 1, "待审核的检查点不能被处置接口删掉"
        db = SessionLocal()
        try:
            row = db.get(Run, run_id)
            assert row.status == "awaiting_review"
            assert row.finished_at is None, "待审核不是终态，不该被写 finished_at"
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            _drop(db, run)
        finally:
            db.close()
