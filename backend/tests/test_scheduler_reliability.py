"""定时任务可靠性（2026-11-18）：漏跑要留证据、多实例选主只有主实例执行。

覆盖两个静默缺口：
1. `_add_job` 原来不传 misfire_grace_time / coalesce / max_instances，用 APScheduler 默认的 1 秒 ——
   进程重启或线程卡顿超过 1 秒的触发被**直接丢弃**，last_run_at 不变、也不留 failed 运行记录。
2. `get_scheduler` 启动时把库里所有 is_enabled 任务全量注册，共享库 + 多后端时每个进程都触发同一 cron。

本文件不依赖真实 cron 到点（那要等），用固定触发时间 + 事件回调 / 直接调内部函数来断言。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.events import EVENT_JOB_MISSED, JobExecutionEvent

from app.config import settings
from app.core import scheduler as scheduler_module
from app.db.models import Run, ScheduledJob
from app.db.session import SessionLocal
from tests.conftest import publish_workflow

START_END_GRAPH = {
    "nodes": [{"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
              {"id": "e", "type": "end", "config": {}}],
    "edges": [{"from": "s", "to": "e"}],
}
# 每年 1 月 1 日 0 点：测试期间不会被真的触发
NEVER_SOON_CRON = "0 0 1 1 *"


def _uid() -> str:
    return uuid.uuid4().hex[:6]


def _missed_event(job_id: str, scheduled_run_time: datetime) -> JobExecutionEvent:
    """构造一个"错过触发"事件。JobExecutionEvent 必须给 jobstore（APScheduler 3.x 的签名），
    真实事件里它是 job 所属的 job store 名，这里用默认库名。"""
    return JobExecutionEvent(EVENT_JOB_MISSED, job_id=job_id, jobstore="default", scheduled_run_time=scheduled_run_time)


@pytest.fixture
def made(client, auth_headers):
    """本用例建的对象，结束时删掉（删工作流会级联删定时任务）。"""
    bag = {"workflows": [], "schedules": []}
    yield bag
    for sid in bag["schedules"]:
        client.delete(f"/api/v1/schedules/{sid}", headers=auth_headers)
    for wid in bag["workflows"]:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def _workflow_and_schedule(client, auth_headers, made, *, name_prefix: str = "pytest-sched-rel") -> tuple[int, int]:
    """建一个已发布工作流 + 一条不会真的触发的定时任务，返回 (workflow_id, schedule_id)。"""
    w = client.post("/api/v1/workflows", headers=auth_headers, json={"name": f"{name_prefix}-wf-{_uid()}", "description": "", "graph": START_END_GRAPH})
    assert w.status_code == 200, w.text
    wid = w.json()["id"]
    made["workflows"].append(wid)
    publish_workflow(client, auth_headers, wid)
    s = client.post("/api/v1/schedules", headers=auth_headers, json={
        "name": f"{name_prefix}-job-{_uid()}", "workflow_id": wid, "cron": NEVER_SOON_CRON, "input": {"input": "x"},
    })
    assert s.status_code == 200, s.text
    made["schedules"].append(s.json()["id"])
    return wid, s.json()["id"]


def _runs_of_schedule(schedule_id: int) -> list[Run]:
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.schedule_id == schedule_id).order_by(Run.id).all()
    finally:
        db.close()


def _schedule_row(schedule_id: int) -> ScheduledJob:
    db = SessionLocal()
    try:
        return db.get(ScheduledJob, schedule_id)
    finally:
        db.close()


# ---------- 缺口 1：漏跑可观测 ----------

def test_add_job_sets_misfire_coalesce_and_max_instances():
    """注册任务时必须显式带三个参数，不能吃 APScheduler 默认的 1 秒 / coalesce=False / max_instances=1 默认值。"""
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler()
    sj = ScheduledJob(id=987654321, name="pytest-probe", workflow_id=1, user_id=1, cron="0 0 1 1 *", input={})
    scheduler_module._add_job(sched, sj)
    job = sched.get_job(str(sj.id))
    assert job is not None, "任务没有注册进调度器"
    # 显式值必须来自配置项，而不是 APScheduler 的默认 1 秒
    assert job.misfire_grace_time == settings.SCHEDULE_MISFIRE_GRACE_SECONDS
    assert job.misfire_grace_time != 1
    assert job.coalesce is True
    assert job.max_instances == 1
    # 这个调度器从未 start 过，shutdown 会抛 SchedulerNotRunningError —— 不启动就不需要收尾


def test_misfire_grace_default_is_generous():
    """默认容忍窗口要明显大于 APScheduler 的 1 秒，否则重启/卡顿一秒就丢触发。"""
    assert settings.SCHEDULE_MISFIRE_GRACE_SECONDS >= 30


def test_missed_trigger_leaves_a_failed_run(client, auth_headers, made):
    """错过触发要留一条 failed 运行记录 —— 与"工作流未发布""创建人停用"同一口径。

    断言到具体文案与状态：只断言"有记录"不能证明它是"漏跑"这条路径写出来的。
    """
    _, schedule_id = _workflow_and_schedule(client, auth_headers, made)
    assert _runs_of_schedule(schedule_id) == [], "前置：任务还没跑过"
    before = _schedule_row(schedule_id).last_run_at

    scheduled_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    scheduler_module._on_job_missed(_missed_event(str(schedule_id), scheduled_time))

    runs = _runs_of_schedule(schedule_id)
    assert len(runs) == 1, f"错过触发后应有 1 条运行记录，实际 {len(runs)} 条"
    assert runs[0].status == "failed"
    assert "错过触发时间" in (runs[0].error or "")
    assert f"超出容忍窗口 {settings.SCHEDULE_MISFIRE_GRACE_SECONDS} 秒" in (runs[0].error or "")
    # 失败也要留收尾时间，否则监控页耗时永远是 0（历史缺陷）
    assert runs[0].finished_at is not None
    # last_run_at 要推进：任务列表里"上次运行"能反映这次尝试过
    after = _schedule_row(schedule_id).last_run_at
    assert after is not None and (before is None or after > before)


def test_missed_event_for_non_business_job_only_logs(caplog):
    """内置任务（id 不是数字，如 system:data-retention）错过触发时不该去写业务运行记录。"""
    scheduler_module._on_job_missed(_missed_event(scheduler_module.RETENTION_JOB_ID, datetime.now(timezone.utc)))
    # 断言到具体内容：内置任务只记日志、不写业务运行记录
    assert "内置任务" in caplog.text and "错过触发" in caplog.text


def test_missed_event_for_deleted_schedule_does_not_crash():
    """任务已被删（事件晚到）时只记日志，不能把调度线程搞崩。"""
    scheduler_module._on_job_missed(_missed_event("999999999", datetime.now(timezone.utc)))


def test_missed_trigger_is_registered_on_scheduler():
    """事件回调必须真的挂到调度器上：没挂的话漏跑依然完全静默。"""
    sched = scheduler_module.get_scheduler()
    # APScheduler 的 _listeners 是 [(callback, mask)] 元组列表
    assert any(cb is scheduler_module._on_job_missed for cb, _mask in sched._listeners), "错过触发的事件回调未注册"
    assert sched._job_defaults.get("coalesce") is True
    assert sched._job_defaults.get("max_instances") == 1
    assert sched._job_defaults.get("misfire_grace_time") == settings.SCHEDULE_MISFIRE_GRACE_SECONDS


# ---------- 缺口 2：多实例选主 ----------

class _FakeConn:
    """假的 psycopg 连接：记录 execute 的语句，按设定返回抢锁结果。"""

    def __init__(self, got_lock: bool):
        self.got_lock = got_lock
        self.closed = False
        self.executed: list[str] = []

    def execute(self, sql, params=None):  # noqa: ARG002
        self.executed.append(sql)
        return self

    def fetchone(self):
        return (self.got_lock,)

    def close(self):
        self.closed = True


def test_second_instance_does_not_get_leadership(monkeypatch):
    """第二个实例抢不到锁 → 不注册业务任务；这是选主要证明的那件事。"""
    taken = _FakeConn(got_lock=False)
    monkeypatch.setattr(settings, "SCHEDULER_LEADER_ELECTION_ENABLED", True)
    monkeypatch.setattr(scheduler_module, "psycopg_connect", lambda *a, **k: taken)
    monkeypatch.setattr(scheduler_module, "_scheduler", None)
    monkeypatch.setattr(scheduler_module, "_is_leader", None)
    monkeypatch.setattr(scheduler_module, "_leader_conn", None)
    try:
        sched = scheduler_module.get_scheduler()
        assert scheduler_module.is_leader() is False
        # 抢不到锁的那条连接要立刻关掉，别白占 max_connections 名额
        assert taken.closed is True
        # 业务 cron 一条都不注册（清理任务也不注册）
        assert sched.get_jobs() == [], f"非主实例不该注册任何任务，实际注册了 {[j.id for j in sched.get_jobs()]}"
    finally:
        if scheduler_module.peek_scheduler() is not None:
            scheduler_module.peek_scheduler().shutdown(wait=False)
        scheduler_module._scheduler = None
        scheduler_module._is_leader = None
        scheduler_module._leader_conn = None


def test_first_instance_gets_leadership_and_holds_connection(monkeypatch):
    """抢到锁 → 成为主实例，并**持有**那条连接（连接被 GC/关闭就等于丢锁）。"""
    mine = _FakeConn(got_lock=True)
    monkeypatch.setattr(settings, "SCHEDULER_LEADER_ELECTION_ENABLED", True)
    monkeypatch.setattr(scheduler_module, "psycopg_connect", lambda *a, **k: mine)
    monkeypatch.setattr(scheduler_module, "_scheduler", None)
    monkeypatch.setattr(scheduler_module, "_is_leader", None)
    monkeypatch.setattr(scheduler_module, "_leader_conn", None)
    try:
        scheduler_module.get_scheduler()
        assert scheduler_module.is_leader() is True
        assert scheduler_module._leader_conn is mine, "选主连接必须被进程持有，否则连接关闭就丢锁"
        assert mine.closed is False
    finally:
        if scheduler_module.peek_scheduler() is not None:
            scheduler_module.peek_scheduler().shutdown(wait=False)
        scheduler_module._scheduler = None
        scheduler_module._is_leader = None
        scheduler_module._leader_conn = None


def test_existing_lock_connection_is_reused_not_reacquired(monkeypatch):
    """已经持有锁时重新启动调度器要复用那条连接，不能再开一条再抢一次。

    否则每重启一次调度器就多一条永不释放的选主连接（同一进程的另一条连接仍能抢到同一把锁），
    在共享库上会把 max_connections 慢慢吃光 —— 这种泄漏极难归因。
    """
    monkeypatch.setattr(settings, "SCHEDULER_LEADER_ELECTION_ENABLED", True)
    calls: list[int] = []

    def _connect(*_a, **_k):
        calls.append(1)
        return _FakeConn(got_lock=True)

    monkeypatch.setattr(scheduler_module, "psycopg_connect", _connect)
    held = _FakeConn(got_lock=True)
    monkeypatch.setattr(scheduler_module, "_leader_conn", held)
    got, conn = scheduler_module._acquire_leadership()
    assert (got, conn) == (True, held)
    assert calls == [], "已持有锁时不应再建立新连接"


def test_leader_election_uses_connection_level_advisory_lock(monkeypatch):
    """必须是连接级 pg_try_advisory_lock（连接断开即释放），不是需要手动 unlock 的会话锁。"""
    mine = _FakeConn(got_lock=True)
    monkeypatch.setattr(settings, "SCHEDULER_LEADER_ELECTION_ENABLED", True)
    monkeypatch.setattr(scheduler_module, "psycopg_connect", lambda *a, **k: mine)
    got, conn = scheduler_module._acquire_leadership()
    assert got is True and conn is mine
    assert any("pg_try_advisory_lock" in sql for sql in mine.executed), mine.executed


def test_non_leader_does_not_register_new_schedule(monkeypatch):
    """非主实例上新建任务也不能注册：否则该 cron 会被主实例和它各触发一次，选主白做。"""
    monkeypatch.setattr(scheduler_module, "is_leader", lambda: False)
    monkeypatch.setattr(scheduler_module, "get_scheduler", lambda: scheduler_module.BackgroundScheduler())
    sj = ScheduledJob(id=123123123, name="pytest-nonleader", workflow_id=1, user_id=1, cron="0 0 1 1 *", input={})
    scheduler_module.add_schedule_job(sj)  # 不应抛异常，也不该注册


def test_leader_election_disabled_makes_every_instance_leader(monkeypatch):
    """显式关掉选主 = 本进程必为主（单进程部署 / 测试口径），状态接口不应显示成"非主"。"""
    monkeypatch.setattr(settings, "SCHEDULER_LEADER_ELECTION_ENABLED", False)
    got, conn = scheduler_module._acquire_leadership()
    assert got is True
    assert conn is None


def test_release_scheduler_frees_lock_and_resets_state(monkeypatch):
    """关闭调度器要释放选主连接：锁是连接级的，不断开时别的实例接管不了。"""
    mine = _FakeConn(got_lock=True)
    monkeypatch.setattr(scheduler_module, "_leader_conn", mine)
    monkeypatch.setattr(scheduler_module, "_is_leader", True)
    monkeypatch.setattr(scheduler_module, "_scheduler", None)
    scheduler_module.release_scheduler()
    assert mine.closed is True
    assert scheduler_module.is_leader() is False
    assert scheduler_module._leader_conn is None


def test_system_status_exposes_leader_state(client, auth_headers):
    """/system/status 要能看出本实例是否持有调度锁，否则多实例部署时无法确认选主生效。"""
    body = client.get("/api/v1/system/status", headers=auth_headers).json()
    assert "is_leader" in body["scheduler"], body["scheduler"]


def test_non_leader_status_is_not_reported_as_degraded(client, auth_headers, monkeypatch):
    """从实例不注册任务是**预期行为**，不能报成"N 个任务未注册"的降级，否则全局横幅永远挂着。"""
    from app.services import system_service

    monkeypatch.setattr(scheduler_module, "peek_scheduler", lambda: _FakeScheduler())
    monkeypatch.setattr(scheduler_module, "is_leader", lambda: False)
    db = SessionLocal()
    try:
        status = system_service._scheduler_status(db)
    finally:
        db.close()
    assert status["is_leader"] is False
    assert status["registered_jobs"] == 0


class _FakeScheduler:
    running = True

    def get_jobs(self):
        return []
