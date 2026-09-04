"""定时任务调度：基于 APScheduler 的 BackgroundScheduler，把 DB 中启用的 ScheduledJob 注册为 cron 触发。

调度任务运行在调度器的独立后台线程中，线程内用 SessionLocal 自建数据库会话，
与请求线程的会话隔离，也没有请求上下文（request_id 为 "-"）。
"""
import logging
from datetime import datetime, timezone

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.models import ScheduledJob, User, Workflow
from app.db.session import SessionLocal
from app.services import run_service, workflow_service

logger = logging.getLogger(__name__)

# 懒加载单例：首次 get_scheduler() 才创建并启动调度线程，避免模块导入即拉起线程
_scheduler = None


def _run_scheduled_job(job_id: int) -> None:
    """定时触发一次工作流。

    与接口触发共用 workflow_service.execute_workflow，thread_id、节点日志、收尾（finished_at/latency_ms）
    行为完全一致。历史上这里自己调 graph.ainvoke 且没传 thread_id，图又绑了 checkpointer，
    每次都在执行前抛错并被静默吞掉，留下大量永远 running 的记录。
    """
    db = SessionLocal()
    try:
        sj = db.get(ScheduledJob, job_id)
        if sj is None or not sj.is_enabled:
            logger.info("定时任务 %s 不存在或已停用，跳过", job_id)
            return
        wf = db.get(Workflow, sj.workflow_id)
        if wf is None:
            logger.warning("定时任务 %s 引用的工作流 %s 不存在，跳过", job_id, sj.workflow_id)
            return
        user = db.get(User, sj.user_id) if sj.user_id else None
        if user is None:
            # runs.user_id 非空；没有有效创建者的任务无法记账，跳过并提示
            logger.warning("定时任务 %s 没有有效的创建者，跳过", job_id)
            return

        input_text = (sj.input or {}).get("input", "")
        run = run_service.create_run(
            db, "workflow", user.id, workflow_id=wf.id, input_data={"scheduled": True, "input": input_text},
        )
        result = workflow_service.execute_workflow(db, wf, run, {"input": input_text, "steps": []}, role=user.role)
        sj.last_run_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("定时任务 %s 执行完成 run_id=%s status=%s", job_id, run.id, result.get("status"))
    except Exception:
        db.rollback()
        logger.exception("定时任务 %s 执行异常", job_id)
    finally:
        db.close()


def _add_job(sched: BackgroundScheduler, sj: ScheduledJob) -> None:
    try:
        trigger = CronTrigger.from_crontab(sj.cron)
    except ValueError:
        # cron 表达式非法的任务不注册；只记日志不抛，避免一条坏数据拖垮调度器启动
        logger.warning("定时任务 %s 的 cron 表达式非法，未注册: %r", sj.id, sj.cron)
        return
    sched.add_job(_run_scheduled_job, trigger, args=[sj.id], id=str(sj.id), replace_existing=True)


def get_scheduler() -> BackgroundScheduler:
    """获取全局调度器（懒启动）：首次调用创建并启动 BackgroundScheduler，
    并把 DB 中所有启用中的定时任务注册进去；后续调用直接返回同一实例。
    注意：本函数会启动独立后台线程，应在应用启动阶段调用。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
        db = SessionLocal()
        try:
            jobs = db.query(ScheduledJob).filter(ScheduledJob.is_enabled == True).all()  # noqa: E712
            for sj in jobs:
                _add_job(_scheduler, sj)
        finally:
            db.close()
    return _scheduler


def add_schedule_job(sj: ScheduledJob) -> None:
    """新增/更新定时任务后调用：把任务注册进调度器。

    cron 表达式非法时只记日志不抛异常，避免单条坏数据影响调度器启动与其余任务。
    """
    _add_job(get_scheduler(), sj)


def remove_schedule_job(job_id: int) -> None:
    """停用/删除定时任务时调用：从调度器移除任务；任务本就未注册时静默通过（幂等删除）。"""
    try:
        get_scheduler().remove_job(str(job_id))
    except JobLookupError:
        # 任务本就未注册（如 cron 非法或已被停用），删除是幂等的，属正常情况
        pass
