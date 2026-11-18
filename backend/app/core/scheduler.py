"""定时任务调度：基于 APScheduler 的 BackgroundScheduler，把 DB 中启用的 ScheduledJob 注册为 cron 触发。

调度任务运行在调度器的独立后台线程中，线程内用 SessionLocal 自建数据库会话，
与请求线程的会话隔离，也没有请求上下文（request_id 为 "-"）。

多实例选主（2026-11-18）：共享库 + 多后端进程时，每个进程都会把库里全部 is_enabled 任务注册一遍，
同一条 cron 被 N 个进程各触发一次 —— 工作流重复执行、模型费用翻 N 倍。
这里用 PostgreSQL **连接级** advisory lock 做进程级选主：抢到锁的实例才注册并执行定时任务，
其余实例不注册、只在 /system/status 里如实报"未持有调度锁"。
选连接级（pg_try_advisory_lock）而不是事务级/会话锁：锁跟着数据库连接的生命周期走，
进程崩溃、连接被 TCP keepalive 判死后由服务端自动释放，不会永久占住；也不需要谁去记得 unlock。
"""
import logging
import time
from datetime import datetime, timezone

from apscheduler.events import EVENT_JOB_MISSED
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from psycopg import OperationalError as PsycopgOperationalError
from psycopg import connect as psycopg_connect

from app.config import settings
from app.core.exceptions import BizError
from app.db.models import ScheduledJob, User
from app.runtime.workflow_config import resolve_live_config
from app.workflow.checkpointer import libpq_dsn
from app.workflow.io_contract import build_initial_state
from app.db.session import SessionLocal
from app.services import run_service, workflow_service

logger = logging.getLogger(__name__)

# 懒加载单例：首次 get_scheduler() 才创建并启动调度线程，避免模块导入即拉起线程
_scheduler = None
# 选主用的长连接：连接活着锁就在，连接断了锁自动释放。整个进程生命周期内保持打开，
# 因此必须显式持有引用（被 GC 回收 = 连接关闭 = 锁丢失，调度器会在无锁状态下继续跑）。
_leader_conn = None
# 本进程是否持有调度锁；None 表示还没尝试过选主（调度器未启动）
_is_leader: bool | None = None

# advisory lock 的键：任意固定的 64 位整数，只要全平台一致即可。
# 取 "AGENT-PLATFORM SCHEDULER" 的 ASCII 前 8 字节转大端整数，便于人工对照，避免与别的系统撞键。
SCHEDULER_LOCK_KEY = 0x4147454E54534348  # b"AGENTSC H"
LOCK_ACQUIRE_ATTEMPTS = 3
LOCK_RETRY_INTERVAL_SECONDS = 2


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


def _record_missed_run(job_id: int, scheduled_run_time: datetime | None) -> None:
    """错过触发时留一条 failed 运行记录，让"任务没跑"在任务列表与运行记录里看得见。

    为什么必须留记录：APScheduler 默认 misfire_grace_time=1 秒，进程重启或调度线程被长任务占住
    超过 1 秒，那次触发就被**直接丢弃** —— 既不调 _run_scheduled_job，也不写任何库记录，
    last_run_at 不变。使用者看到的是"配了任务但没跑"，服务端只有一行没人看的 APScheduler 日志。
    这与本文件里"工作流未发布""创建人停用"刻意留 failed 运行的做法是同一个口径：
    无人值守的任务，任何一次没执行都要有可查的证据。

    没有有效创建者时无法建运行记录（runs.user_id 非空），只能记日志 —— 与 _run_scheduled_job 的同类分支一致。
    """
    db = SessionLocal()
    try:
        sj = db.get(ScheduledJob, job_id)
        if sj is None:
            logger.warning("定时任务 %s 错过触发，但任务已不存在，无法记账", job_id)
            return
        user = db.get(User, sj.user_id) if sj.user_id else None
        if user is None:
            logger.warning("定时任务 %s 错过触发，且没有有效的创建者，无法记账", job_id)
            return
        delay = "未知"
        if scheduled_run_time is not None:
            delay = f"{max(0, int((datetime.now(timezone.utc) - scheduled_run_time).total_seconds()))} 秒"
        run = run_service.create_run(
            db, "workflow", user.id, workflow_id=sj.workflow_id, input_data={"inputs": sj.input or {}},
            source="schedule", schedule_id=sj.id,
        )
        run_service.finalize_run(
            db, run, "failed",
            error=f"错过触发时间（延迟 {delay}，超出容忍窗口 {settings.SCHEDULE_MISFIRE_GRACE_SECONDS} 秒），本次未执行",
        )
        sj.last_run_at = datetime.now(timezone.utc)
        db.commit()
        logger.warning("定时任务 %s 错过触发，已留 failed 运行记录 run_id=%s 延迟=%s", job_id, run.id, delay)
    except Exception:
        db.rollback()
        # 记账失败不能拖垮调度线程（这里跑在 APScheduler 的事件回调里）；
        # 但也绝不能静默：留完整堆栈，运维能据此知道"这条错过没记上"
        logger.exception("定时任务 %s 错过触发后写运行记录失败", job_id)
    finally:
        db.close()


def _on_job_missed(event) -> None:
    """APScheduler 事件回调：触发时间已过且超出 misfire_grace_time，APScheduler 放弃了这次触发。

    这是"漏跑"唯一能被程序捕获的时机 —— 函数根本没被调用，只能靠事件。
    job_id 不是业务定时任务的（如内置清理任务）时只记日志。
    """
    job_id = event.job_id
    if not str(job_id).isdigit():
        logger.warning("内置任务 %s 错过触发（延迟超过容忍窗口），本次跳过", job_id)
        return
    _record_missed_run(int(job_id), getattr(event, "scheduled_run_time", None))


# 三个参数显式传，不依赖 APScheduler 默认值（2026-11-18）：
# - misfire_grace_time：默认 1 秒太紧，进程重启/线程卡顿超过 1 秒就静默丢弃该次触发。走配置项。
# - coalesce=True：停机后恢复时，同一任务积压的多次触发只补跑一次。
#   否则停机两小时、每分钟一次的任务会在恢复瞬间连续触发 120 次，把模型费用和数据库连接一起打爆。
# - max_instances=1：同一任务不允许并发。上一次还没跑完（工作流可能跑几分钟），
#   下一次触发就排队等待，而不是再起一个线程并发跑同一条工作流。
_JOB_DEFAULTS = {
    "misfire_grace_time": settings.SCHEDULE_MISFIRE_GRACE_SECONDS,
    "coalesce": True,
    "max_instances": 1,
}


def _add_job(sched: BackgroundScheduler, sj: ScheduledJob) -> None:
    try:
        trigger = CronTrigger.from_crontab(sj.cron)
    except ValueError:
        # cron 表达式非法的任务不注册；只记日志不抛，避免一条坏数据拖垮调度器启动
        logger.warning("定时任务 %s 的 cron 表达式非法，未注册: %r", sj.id, sj.cron)
        return
    sched.add_job(_run_scheduled_job, trigger, args=[sj.id], id=str(sj.id), replace_existing=True, **_JOB_DEFAULTS)


def release_scheduler() -> None:
    """关闭调度器并释放调度锁（应用关闭钩子调用）。

    顺序不能反：先 shutdown 再释放锁。反过来的话，锁一释放别的实例立刻接管，
    而本进程的调度线程可能还在跑最后一批任务 —— 两边同时跑，正是选主要避免的事。
    """
    global _scheduler
    if _scheduler is None:
        _release_leadership()
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        # 已经停过或内部状态异常：关闭路径不该把进程退出流程拖垮，但要留痕
        logger.warning("关闭调度器失败", exc_info=True)
    finally:
        _scheduler = None
        _release_leadership()


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


def _acquire_leadership():
    """抢调度锁，返回 (是否拿到, 连接对象)。

    用**连接级** advisory lock（pg_try_advisory_lock）：锁归属于那条数据库连接，
    连接断开（进程崩溃、被 keepalive 判死、网络中断）由 PostgreSQL 自动释放，不需要谁去 unlock，
    因此不会出现"进程挂了但锁被永久占住、重启后谁都不干活"的死局。
    不用事务级（pg_try_advisory_xact_lock）：那需要一条长期打开的事务，空闲事务会拖住 vacuum，
    且事务一旦提交/回滚锁就没了，与本函数的生命周期语义不符。

    为什么自己开一条 psycopg 连接而不是用 SQLAlchemy 连接池：
    锁必须挂在一条**活着的、不归还池**的连接上。用池里的连接，commit/rollback 或 close 之后
    连接回到池里可能被别的代码复用，锁的归属就变得不可控；而且池的回收策略会悄悄关掉它。
    复用 checkpointer.libpq_dsn 转 DSN，避免自己再拼一遍连接串（口令的百分号编码容易出错）。
    """
    if not settings.SCHEDULER_LEADER_ELECTION_ENABLED:
        # 显式关掉选主 = 本进程必为主（单进程部署、或测试里要一个确定的行为）。
        # 这里返回 None 连接，is_leader() 仍报 True，状态接口不会把它显示成"非主"。
        logger.info("调度器选主已关闭（SCHEDULER_LEADER_ELECTION_ENABLED=false），本实例直接作为主实例")
        return True, None
    if _leader_conn is not None and not _leader_conn.closed:
        # 已经持有锁（例如测试把 _scheduler 复位后重新启动调度器）：复用那条连接。
        # 不复用就会再开一条连接、再抢一次锁 —— 自己已经持有这把锁，第二次 pg_try_advisory_lock
        # 在同一进程的**另一条连接**上仍然会成功，于是每次重启都多一条永不释放的连接，
        # 把 max_connections 慢慢吃光（这类泄漏只在共享库上才会暴露，很难归因）。
        logger.info("本实例已持有调度锁，复用现有连接")
        return True, _leader_conn
    last_error: Exception | None = None
    for attempt in range(1, LOCK_ACQUIRE_ATTEMPTS + 1):
        try:
            conn = psycopg_connect(libpq_dsn(settings.DATABASE_URL), autocommit=True, connect_timeout=10)
            row = conn.execute("SELECT pg_try_advisory_lock(%s)", (SCHEDULER_LOCK_KEY,)).fetchone()
            if row is not None and row[0]:
                logger.info("本实例已获得调度锁（key=%s），注册并执行定时任务", SCHEDULER_LOCK_KEY)
                return True, conn
            # 没抢到：这条连接立刻关掉，别让它白占一个 max_connections 名额
            conn.close()
            logger.warning("调度锁已被其他实例持有（第 %d/%d 次尝试），本实例不注册定时任务",
                           attempt, LOCK_ACQUIRE_ATTEMPTS)
            return False, None
        except PsycopgOperationalError as e:
            # 连不上库（隧道抖动、库重启）：重试几次；仍失败则按"不是主"处理 ——
            # 宁可这个实例不跑定时任务，也不能在状态未确定时抢跑成第二个主。
            last_error = e
            logger.warning("获取调度锁失败（第 %d/%d 次）：%s", attempt, LOCK_ACQUIRE_ATTEMPTS, e)
            if attempt < LOCK_ACQUIRE_ATTEMPTS:
                time.sleep(LOCK_RETRY_INTERVAL_SECONDS)
    logger.error("多次尝试后仍无法确定调度锁归属，本实例按非主处理，不注册定时任务：%s", last_error)
    return False, None


def is_leader() -> bool | None:
    """本实例是否持有调度锁。None = 调度器还没启动过（没尝试选主），调用方据此区分"未启动"与"非主"。"""
    return _is_leader


def _release_leadership() -> None:
    """关闭选主连接：连接一断，服务端的 advisory lock 自动释放，别的实例下一次启动就能接管。

    显式调 pg_advisory_unlock 不是必需的（关连接就释放），但主动 unlock 能让接管立即发生，
    不用等服务端察觉连接已断（可能要到 keepalive 超时）。失败只记日志：连接可能已经断了。
    """
    global _leader_conn, _is_leader
    conn = _leader_conn
    _leader_conn = None
    _is_leader = False
    if conn is None:
        return
    try:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEDULER_LOCK_KEY,))
    except Exception:
        # 连接已断时 unlock 必然失败，而锁也已随连接断开释放 —— 属预期，记 warning 不留堆栈
        logger.warning("释放调度锁失败（连接可能已断开），锁会随连接关闭自动释放", exc_info=True)
    finally:
        try:
            conn.close()
        except Exception:
            logger.warning("关闭调度锁连接失败", exc_info=True)


def get_scheduler() -> BackgroundScheduler:
    """获取全局调度器（懒启动）：首次调用创建并启动 BackgroundScheduler，
    并在**拿到调度锁**时把 DB 中所有启用中的定时任务注册进去；后续调用直接返回同一实例。

    多实例选主（2026-11-18）：共享库 + 多后端进程时，原来每个进程都会注册并触发同一批 cron，
    工作流重复执行、费用翻倍。现在只有抢到 PostgreSQL advisory lock 的实例注册业务任务，
    其余实例的调度器照常启动（用于"立即执行"这类手动触发），但不注册任何 cron 任务。

    注意：本函数会启动独立后台线程，应在应用启动阶段调用。
    """
    global _scheduler, _leader_conn, _is_leader
    if _scheduler is None:
        _scheduler = BackgroundScheduler(job_defaults=_JOB_DEFAULTS)
        # 监听"错过触发"事件：这是漏跑唯一能被程序捕获的时机（见 _on_job_missed）
        _scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)
        _scheduler.start()
        _is_leader, _leader_conn = _acquire_leadership()
        if _is_leader:
            db = SessionLocal()
            try:
                jobs = db.query(ScheduledJob).filter(ScheduledJob.is_enabled == True).all()  # noqa: E712
                for sj in jobs:
                    _add_job(_scheduler, sj)
            finally:
                db.close()
            _register_retention_job(_scheduler)
        else:
            # 非主实例：一条 cron 都不注册，避免同一条任务被多进程重复触发。
            # 手动"立即执行"（trigger_now）仍然可用，它是一次性的、不产生周期性重复。
            logger.warning("本实例未持有调度锁，不注册定时任务；定时任务由持锁实例执行")
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

    # 同样显式传 misfire/coalesce/max_instances：清理任务漏跑一天，llm_calls 就多积一天的数据
    sched.add_job(_run, CronTrigger(hour=3, minute=10), id=RETENTION_JOB_ID, replace_existing=True, **_JOB_DEFAULTS)


def add_schedule_job(sj: ScheduledJob) -> None:
    """新增/更新定时任务后调用：把任务注册进调度器。

    cron 表达式非法时只记日志不抛异常，避免单条坏数据影响调度器启动与其余任务。
    非主实例不注册（2026-11-18）：否则"在非主实例上新建一个任务"就会让这条 cron
    同时被主实例和它各触发一次 —— 选主就白做了。
    """
    sched = get_scheduler()
    if not is_leader():
        logger.info("本实例未持有调度锁，跳过注册定时任务 %s（由持锁实例执行）", sj.id)
        return
    _add_job(sched, sj)


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
