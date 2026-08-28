import asyncio
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.models import Run, ScheduledJob, Workflow
from app.db.session import SessionLocal
from app.workflow.engine import build_workflow

_scheduler = None


def _run_scheduled_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        sj = db.get(ScheduledJob, job_id)
        if sj is None or not sj.is_enabled:
            return
        wf = db.get(Workflow, sj.workflow_id)
        if wf is None:
            return
        run = Run(run_type="workflow", workflow_id=wf.id, user_id=sj.user_id, status="running",
                  input={"scheduled": True, "input": (sj.input or {}).get("input", "")})
        db.add(run)
        db.commit()
        db.refresh(run)

        graph = build_workflow(wf.graph, run_id=run.id)
        result = asyncio.run(graph.ainvoke({"input": (sj.input or {}).get("input", ""), "steps": []}))

        run.status = "success"
        run.output = {"output": result.get("output")}
        sj.last_run_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _add_job(sched: BackgroundScheduler, sj: ScheduledJob) -> None:
    try:
        trigger = CronTrigger.from_crontab(sj.cron)
        sched.add_job(_run_scheduled_job, trigger, args=[sj.id], id=str(sj.id), replace_existing=True)
    except Exception:
        pass


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
        db = SessionLocal()
        try:
            jobs = db.query(ScheduledJob).filter(ScheduledJob.is_enabled == True).all()
            for sj in jobs:
                _add_job(_scheduler, sj)
        finally:
            db.close()
    return _scheduler


def add_schedule_job(sj: ScheduledJob) -> None:
    _add_job(get_scheduler(), sj)


def remove_schedule_job(job_id: int) -> None:
    try:
        get_scheduler().remove_job(str(job_id))
    except Exception:
        pass
