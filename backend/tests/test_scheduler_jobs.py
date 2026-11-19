"""定时任务执行（core/scheduler.py 的 _run_scheduled_job / _record_missed_run）。

为什么单独测：定时任务**无人值守**，任何一次"没跑"或"跑了一半没记账"都必须留下可查的证据。
本文件逐条覆盖它的每个跳过与失败分支：任务不存在、任务已停用、没有有效创建者、
工作流未发布、创建人已停用、固定输入与声明不符、执行中途抛异常。

这些分支写错的后果都是静默的：任务列表里 last_run_at 不动、运行记录里什么都没有，
使用者只看到"配了任务但没跑"，服务端只有一行没人看的日志。

工作流执行本身打桩（那是 workflow_service 的测试范围），这里只验调度侧的编排与记账。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core import scheduler
from app.core.exceptions import BizError
from app.db.models import Run, ScheduledJob, User, Workflow
from app.db.session import SessionLocal


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def admin(db):
    return db.query(User).filter(User.username == "admin").first()


@pytest.fixture
def workflow(db, admin):
    """一个已发布的空工作流（调度只校验"有线上版本"，不真的执行）。"""
    wf = Workflow(name="pytest-sched-wf-" + uuid.uuid4().hex[:6], description="",
                  graph={"nodes": [], "edges": []}, created_by=admin.id)
    db.add(wf)
    db.commit()
    yield wf
    for job in db.query(ScheduledJob).filter(ScheduledJob.workflow_id == wf.id).all():
        db.delete(job)
    db.commit()
    for run in db.query(Run).filter(Run.workflow_id == wf.id).all():
        db.delete(run)
    db.commit()
    db.delete(wf)
    db.commit()


@pytest.fixture
def job(db, admin, workflow):
    def _make(**kw) -> ScheduledJob:
        sj = ScheduledJob(
            name=kw.get("name", "pytest-sched-" + uuid.uuid4().hex[:6]),
            workflow_id=workflow.id, user_id=kw.get("user_id", admin.id),
            cron=kw.get("cron", "0 9 * * *"), input=kw.get("input", {}),
            is_enabled=kw.get("is_enabled", True),
        )
        db.add(sj)
        db.commit()
        return sj

    return _make


def _runs_of(db, job_id: int) -> list[Run]:
    return db.query(Run).filter(Run.schedule_id == job_id).order_by(Run.id).all()


def _live(graph: dict | None = None):
    """构造一份"线上版本配置"：调度侧只用 version 与 graph 两个字段。"""
    from app.runtime.workflow_config import WorkflowRunConfig

    return WorkflowRunConfig(workflow_id=1, version=1, name="pytest-wf", description="",
                             graph=graph or {"nodes": []})


# --------------------------------------------------------------------------- 跳过：不该建运行记录

def test_missing_job_is_skipped(db):
    """任务已被删：什么都不做，也不能抛异常（它在 APScheduler 的线程里跑）。"""
    scheduler._run_scheduled_job(99999999)


def test_disabled_job_is_skipped_without_force(db, job):
    """停用的任务不跑（force=True 才跑，那是"立即执行"入口）。"""
    sj = job(is_enabled=False)
    scheduler._run_scheduled_job(sj.id)
    assert _runs_of(db, sj.id) == []


def test_job_without_valid_creator_is_skipped(db, job, workflow):
    """没有有效创建者：runs.user_id 非空，记不了账，只能跳过并留日志。"""
    sj = job(user_id=None)
    scheduler._run_scheduled_job(sj.id)
    assert _runs_of(db, sj.id) == []


# --------------------------------------------------------------------------- 失败要留 failed 运行

def test_unpublished_workflow_leaves_failed_run(db, job, monkeypatch):
    """工作流取不到线上版本：留一条 failed，让"为什么这次没跑"在运行记录里看得见。"""
    def _boom(db_, wf_id):
        raise BizError(400, "工作流未发布")

    monkeypatch.setattr(scheduler, "resolve_live_config", _boom)
    sj = job()
    scheduler._run_scheduled_job(sj.id)
    runs = _runs_of(db, sj.id)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "工作流不可运行" in runs[0].error
    assert "工作流未发布" in runs[0].error
    db.refresh(sj)
    assert sj.last_run_at is not None, "失败也要更新 last_run_at，否则列表上看不出跑过"


def test_inactive_creator_leaves_failed_run(db, job, monkeypatch):
    """创建人已停用：不再以其身份执行，但要留 failed 记录。"""
    from app.runtime import workflow_config

    monkeypatch.setattr(scheduler, "resolve_live_config", lambda db_, wf_id: _live())
    sj = job()
    user = db.get(User, sj.user_id)
    user.is_active = False
    db.commit()
    try:
        scheduler._run_scheduled_job(sj.id)
        runs = _runs_of(db, sj.id)
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert "创建人已停用" in runs[0].error
    finally:
        user.is_active = True
        db.commit()


def test_input_mismatch_leaves_failed_run(db, job, monkeypatch):
    """固定输入与开始节点声明不符：留 failed 并带上原因，不静默按"没有输入"跑。"""
    from app.runtime import workflow_config

    monkeypatch.setattr(scheduler, "resolve_live_config", lambda db_, wf_id: _live(
        {"nodes": [{"type": "start", "config": {"variables": [{"name": "required"}]}}]}))
    sj = job(input={})
    scheduler._run_scheduled_job(sj.id)
    runs = _runs_of(db, sj.id)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "固定输入与工作流声明不符" in runs[0].error
    assert "required" in runs[0].error


def test_exception_midway_finalizes_the_run(db, job, monkeypatch):
    """执行中途抛异常：已建的运行记录必须被置 failed，不能留下永久 running 的幽灵记录。"""
    from app.runtime import workflow_config

    monkeypatch.setattr(scheduler, "resolve_live_config", lambda db_, wf_id: _live())

    def _boom(*a, **kw):
        raise RuntimeError("执行炸了")

    monkeypatch.setattr(scheduler.workflow_service, "execute_workflow", _boom)
    sj = job()
    scheduler._run_scheduled_job(sj.id)
    runs = _runs_of(db, sj.id)
    assert len(runs) == 1
    db.refresh(runs[0])
    assert runs[0].status == "failed"
    assert "执行异常" in runs[0].error


def test_successful_run_updates_last_run_at(db, job, monkeypatch):
    from app.runtime import workflow_config

    monkeypatch.setattr(scheduler, "resolve_live_config", lambda db_, wf_id: _live())
    monkeypatch.setattr(scheduler.workflow_service, "execute_workflow",
                        lambda *a, **kw: {"status": "success"})
    sj = job()
    scheduler._run_scheduled_job(sj.id)
    db.refresh(sj)
    assert sj.last_run_at is not None


# --------------------------------------------------------------------------- 漏跑记账

def test_missed_run_is_recorded_as_failed(db, job):
    """错过触发必须留 failed 记录：APScheduler 默认直接把那次触发丢掉，不留痕就等于没发生过。"""
    sj = job()
    scheduled_at = datetime.now(timezone.utc)
    scheduler._record_missed_run(sj.id, scheduled_at)
    runs = _runs_of(db, sj.id)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "错过触发时间" in runs[0].error
    assert str(scheduler.settings.SCHEDULE_MISFIRE_GRACE_SECONDS) in runs[0].error


def test_missed_run_without_time_says_unknown(db, job):
    """拿不到计划触发时刻时写"未知"，不能编一个 0 秒延迟。"""
    sj = job()
    scheduler._record_missed_run(sj.id, None)
    runs = _runs_of(db, sj.id)
    assert "未知" in runs[0].error


def test_missed_run_for_deleted_job_is_ignored(db):
    """任务已删除：记不了账，也不能抛（它在事件回调里，抛了会影响调度线程）。"""
    scheduler._record_missed_run(99999999, datetime.now(timezone.utc))


def test_missed_run_without_creator_is_ignored(db, job):
    sj = job(user_id=None)
    scheduler._record_missed_run(sj.id, datetime.now(timezone.utc))
    assert _runs_of(db, sj.id) == []


# --------------------------------------------------------------------------- 选主

def test_is_leader_reflects_state(monkeypatch):
    """is_leader 要如实反映"本进程有没有抢到调度锁"：状态页据此告诉运维为什么任务没跑。"""
    monkeypatch.setattr(scheduler, "_is_leader", True)
    assert scheduler.is_leader() is True
    monkeypatch.setattr(scheduler, "_is_leader", False)
    assert scheduler.is_leader() is False
    monkeypatch.setattr(scheduler, "_is_leader", None)
    assert scheduler.is_leader() is None
