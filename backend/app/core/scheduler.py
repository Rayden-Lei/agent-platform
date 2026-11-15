"""定时任务调度：基于 APScheduler 的 BackgroundScheduler，把 DB 中启用的 ScheduledJob 注册为 cron 触发。

调度任务运行在调度器的独立后台线程中，线程内用 SessionLocal 自建数据库会话，
与请求线程的会话隔离，也没有请求上下文（request_id 为 "-"）。
"""
import logging
from datetime import datetime, timezone

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.exceptions import BizError
from app.db.models import ScheduledJob, User
from app.runtime.workflow_config import resolve_live_config
from app.workflow.io_contract import build_initial_state
from app.db.session import SessionLocal
from app.services import run_service, workflow_service

logger = logging.getLogger(__name__)

# 懒加载单例：首次 get_scheduler() 才创建并启动调度线程，避免模块导入即拉起线程
_scheduler = None


def _run_scheduled_job(job_id: int, force: bool = False) -> None:
    """定时触发一次工作流。force=True 是"立即执行"入口：停用的任务也跑，便于验证配置。

    与接口触发共用 workflow_service.execute_workflow，thread_id、节点日志、收尾（finished_at/latency_ms）
    行为完全一致。历史上这里自己调 graph.ainvoke 且没传 thread_id，图又绑了 checkpointer，
    每次都在执行前抛错并被静默吞掉，留下大量永远 running 的记录。
    """
    db = SessionLocal()
    run = None
    try:
        sj = db.get(ScheduledJob, job_id)
        if sj is None or (not sj.is_enabled and not force):
            logger.info("定时任务 %s 不存在或已停用，跳过", job_id)
            return
        user = db.get(User, sj.user_id) if sj.user_id else None
        if user is None:
            # runs.user_id 非空；没有有效创建者的任务无法记账，跳过并提示
            logger.warning("定时任务 %s 没有有效的创建者，跳过", job_id)
            return

        # 定时任务保存的就是"运行入参字典"本身（{变量名: 值}），与 POST /run 的 inputs 同一份结构
        scheduled_inputs = sj.input or {}
        # **读线上发布版本，不读草稿**（FR-075）：定时任务保存时已校验过"工作流已发布"，
        # 但之后工作流可能被删除或从未发布（迁移漏了），这里按线上版本执行，改草稿不影响已有任务。
        # 取不到线上版本时留一条 failed 运行：任务列表与运行记录里看得到"为什么这次没跑"，
        # 而不是只在服务端日志里留一行没人看的 warning。
        try:
            live = resolve_live_config(db, sj.workflow_id)
        except BizError as e:
            run = run_service.create_run(
                db, "workflow", user.id, workflow_id=sj.workflow_id, input_data={"inputs": scheduled_inputs},
                source="schedule", schedule_id=sj.id,
            )
            run_service.finalize_run(db, run, "failed", error=f"工作流不可运行：{e.detail}")
            sj.last_run_at = datetime.now(timezone.utc)
            db.commit()
            logger.warning("定时任务 %s 的%s，未执行", job_id, e.detail)
            return
        run = run_service.create_run(
            db, "workflow", user.id, workflow_id=sj.workflow_id, input_data={"inputs": scheduled_inputs},
            source="schedule", schedule_id=sj.id, workflow_version=live.version,
        )
        if not user.is_active:
            # 停用账号的任务不再以其身份执行（API Key 路径同样拒绝停用账号，2026-10-05 前这里只判存在）；
            # 留一条 failed 运行，任务列表与运行记录里看得到为什么没跑
            run_service.finalize_run(db, run, "failed", error="创建人已停用，任务未执行")
            sj.last_run_at = datetime.now(timezone.utc)
            db.commit()
            logger.warning("定时任务 %s 的创建人 %s 已停用，未执行", job_id, user.id)
            return
        # 定时任务的固定输入按开始节点声明校验（docs/15 WF-04）：声明改了而任务里还填着旧变量时，
        # 这里抛 400，运行记录被置 failed 并带上原因——不静默按"没有输入"跑
        try:
            initial = build_initial_state(live.graph, scheduled_inputs)
        except BizError as e:
            run_service.finalize_run(db, run, "failed", error=f"定时任务的固定输入与工作流声明不符：{e.detail}")
            sj.last_run_at = datetime.now(timezone.utc)
            db.commit()
            logger.warning("定时任务 %s 的固定输入不合法，未执行：%s", job_id, e.detail)
            return
        result = workflow_service.execute_workflow(db, sj.workflow_id, live.version, initial, run, role=user.role)
        sj.last_run_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("定时任务 %s 执行完成 run_id=%s status=%s", job_id, run.id, result.get("status"))
    except Exception:
        db.rollback()
        # 兜底：若已创建运行记录却因后续异常未收尾（execute_workflow 正常路径不会抛，
        # 但 last_run_at 提交等环节仍可能失败），把它置为 failed，避免遗留永久 running 的幽灵记录
        if run is not None:
            try:
                run_service.finalize_run(db, run, "failed", error="定时任务执行异常")
            except Exception:
                logger.exception("定时任务 %s 异常后收尾运行记录失败 run_id=%s", job_id, run.id)
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


def peek_scheduler() -> BackgroundScheduler | None:
    """只看调度器**是否已在跑**，不启动它；未启动返回 None。

    为什么要这个只读入口：`GET /system/status` 与 `GET /stats/overview` 都是只读接口，
    但它们内部调 `get_system_status()` → `get_scheduler()`，而后者是"懒启动"——
    一个探活请求就会拉起后台线程、把库里所有启用任务注册进来。

    后果不是性能问题而是**副作用藏在读接口里**：
    - 测试里本该由 lifespan 控制的调度器，被某个读用例意外启动，之后所有用例都在有调度器的
      进程里跑（隐藏耦合，且顺序一变就飘）；
    - 哪天要"关掉调度器跑单进程"，一个探活请求就把它拉起来了。

    状态展示只关心"已启动的话注册了几个"，用这个函数就够。
    """
    return _scheduler


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
        _register_retention_job(_scheduler)
    return _scheduler


# 内置系统任务的 id 前缀：与业务定时任务（id 是数字字符串）区分开，
# 这样 remove_schedule_job 之类按数字 id 操作的方法不会误删它。
RETENTION_JOB_ID = "system:data-retention"


def _register_retention_job(sched: BackgroundScheduler) -> None:
    """注册数据保留清理任务（每天 03:10 跑一次）。

    为什么挂在应用调度器里而不是系统 cron：清理逻辑要读应用配置（保留天数、开关）
    并用应用的连接池，放系统 cron 里等于把配置与连接参数再维护一份。

    为什么是 03:10：避开业务高峰，也避开整点 —— 整点是各种备份、日志轮转聚集的时刻，
    同一时刻抢数据库锁的概率最高。
    """
    from app.services.retention_service import purge_expired

    def _run() -> None:
        try:
            purge_expired()
        except Exception:
            # 清理失败必须留痕：静默失败会让 llm_calls 悄悄涨到撑爆磁盘
            logger.exception("数据保留清理失败")

    sched.add_job(_run, CronTrigger(hour=3, minute=10), id=RETENTION_JOB_ID, replace_existing=True)


def add_schedule_job(sj: ScheduledJob) -> None:
    """新增/更新定时任务后调用：把任务注册进调度器。

    cron 表达式非法时只记日志不抛异常，避免单条坏数据影响调度器启动与其余任务。
    """
    _add_job(get_scheduler(), sj)


def is_valid_cron(expr: str) -> bool:
    """cron 表达式是否可被调度器解析（五段 crontab 语法）。"""
    try:
        CronTrigger.from_crontab(expr)
        return True
    except ValueError:
        return False


def next_run_times(job_ids: list[int]) -> dict[int, datetime | None]:
    """一次读取多个任务的下次触发时间；未注册（停用 / cron 非法 / 调度器未启动）为 None。只反映本进程的调度器。"""
    sched = get_scheduler()
    result: dict[int, datetime | None] = {}
    for job_id in job_ids:
        job = sched.get_job(str(job_id))
        result[job_id] = job.next_run_time if job else None
    return result


def trigger_now(job_id: int, force: bool = False) -> None:
    """立即执行一次定时任务（在调度器线程池里跑，不阻塞请求）；force 让停用的任务也能手动跑一次。"""
    get_scheduler().add_job(
        _run_scheduled_job, args=[job_id], kwargs={"force": force},
        id=f"manual-{job_id}-{datetime.now(timezone.utc).timestamp()}", replace_existing=False,
    )


def remove_schedule_job(job_id: int) -> None:
    """停用/删除定时任务时调用：从调度器移除任务；任务本就未注册时静默通过（幂等删除）。"""
    try:
        get_scheduler().remove_job(str(job_id))
    except JobLookupError:
        # 任务本就未注册（如 cron 非法或已被停用），删除是幂等的，属正常情况
        pass
