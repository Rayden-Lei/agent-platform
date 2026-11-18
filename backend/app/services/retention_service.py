"""数据保留：定期清理只增不减的大表（llm_calls / audit_logs）与工作流检查点。

为什么需要
---------
`llm_calls` 单条可存 256KB 请求 + 256KB 响应（models.py 的 LlmCall 注释写明"要能独立留存"），
审计日志每次写操作一条。两张表都只增不减，一个真实使用的实例几个月就能到 GB 级；
而它们都不是业务数据 —— 清掉旧的不影响任何功能，留着才是隐患（磁盘、备份体积、
以及病历类正文长期明文驻留）。

设计取舍
---------
- **按时间窗删，不按行数**：行数清理在流量波动时不可预期，时间窗好解释也好审计。
- **批量删 + 有界**：一次只删 LIMIT 条，循环直到删不动，避免一条长事务锁表
  （这张表在对话热路径上写入）。
- **可关闭**：`DATA_RETENTION_ENABLED=false` 时任务直接返回，给需要长期留存的部署一个开关。
- **只删超期行**：`DELETE ... WHERE started_at < cutoff LIMIT n`，有索引走索引，无索引也不会全表扫。

工作流检查点（docs/15 WF-12、OP-10）
-----------------------------------
终态运行本该在收尾时删掉自己的检查点（workflow_service.execute_workflow / chat_runner），
但进程被杀、清理失败、旧版本代码都会留下残留 —— 一张图每个节点每次执行都追加一份快照，
`checkpoints` / `checkpoint_blobs` / `checkpoint_writes` 三张表只涨不消，最终撑爆磁盘。
这里按运行记录的终态时间兜底回收，**不碰仍在运行（running）的**：那是活着的执行线程正在写的。

awaiting_review 的检查点是"审批后 resume 找回被 interrupt 的图"的唯一依据，不能按终态那样清；
但没人审批的运行会永久占着一份完整快照。因此只清超过 `CHECKPOINT_AWAITING_REVIEW_RETENTION_DAYS`
仍未审批的，并且**先把运行收尾成 failed 再删检查点** —— 只删检查点不收尾的话，
那条运行会永远停在 awaiting_review，审批一提交就从空 state 重跑（实测行为见
tests/test_checkpoint_postgres.py），用户以为审批生效了其实没有。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.config import settings
from app.db.models import Run
from app.db.session import SessionLocal
from app.services import run_service
from app.workflow.checkpointer import delete_thread_safely

logger = logging.getLogger(__name__)

# 单批删除条数：小一点避免长事务；配合下面的循环直到删空
BATCH_SIZE = 1000
# 单次任务最多跑多少批：防止异常情况下把调度线程占住一整晚(1000 * 200 = 20 万行/次)
MAX_BATCHES = 200
# 检查点每批处理的 thread 数：一次删除走一条 psycopg 连接、一个事务，
# 比 llm_calls 的单批 1000 小得多 —— 每个 thread 的 checkpoint_blobs 可能几十 MB，
# 一批删太多会让这条事务持有大量 WAL，也会长时间占着 checkpointer 连接池的一个槽位。
CHECKPOINT_BATCH = 50

# 超期未审批的运行被自动收尾时写进 runs.error 的原因。
# 与 run_service.STUCK_RUN_REASON 分开写：前者是"人工处置卡住的运行"，这里是"保留期到期自动回收"，
# 排查时要能从 error 直接看出是哪条路径做的。
AWAITING_REVIEW_EXPIRED_REASON = "等待人工审核超过保留期，检查点已回收，运行自动终止"


def _purge(db, table: str, time_column: str, cutoff: datetime, limit: int = BATCH_SIZE) -> int:
    """删一批超期行，返回删除条数。

    表名与列名是本模块的内部常量（不是用户输入），不构成注入面；
    参数一律绑定，时间值不拼进 SQL。
    """
    sql = text(f'DELETE FROM {table} WHERE id IN ('
               f'SELECT id FROM {table} WHERE {time_column} < :cutoff LIMIT :limit)')
    result = db.execute(sql, {"cutoff": cutoff, "limit": limit})
    db.commit()
    return int(result.rowcount or 0)


def _purge_all(db, table: str, time_column: str, cutoff: datetime) -> int:
    total = 0
    for _ in range(MAX_BATCHES):
        removed = _purge(db, table, time_column, cutoff)
        total += removed
        if removed < BATCH_SIZE:
            break
    else:
        logger.warning("清理 %s 达到单次上限 %d 批，剩余部分留到下次", table, MAX_BATCHES)
    return total


def _checkpoint_threads(db, after: str | None, limit: int) -> list[str]:
    """按 thread_id 升序取一批"库里确实还有检查点"的 thread_id，返回原始字符串。

    **为什么从 checkpoints 侧取候选，而不是从 runs 侧按 id 扫**：终态运行本该在收尾时就删掉自己的
    检查点，残留是少数。从 runs 侧按 id 升序取"超期终态运行"，会永远从最小的那批开始，
    而那些运行大多已经没有检查点 —— 结果是一次任务反复对同一批 no-op 删，真正的残留永远轮不到。
    从 checkpoints 侧取，候选就是"真的有行要删"的，删一个少一个，游标能真正往前推进。

    这里直接读 langgraph 的 checkpoints 表（thread_id 即 runs.id）：该表结构由
    langgraph-checkpoint-postgres 决定，没有时间列，不能加列，也无法用 ORM 表达。
    checkpointer 模块同样直接读它（open_checkpointer 的探活），口径一致。
    """
    sql = "SELECT DISTINCT thread_id FROM checkpoints"
    params: dict = {"limit": limit}
    if after is not None:
        # 游标按 thread_id 升序推进：删掉的不会再出现，没删的（running / 未超期）会被下一轮的
        # 全量重扫覆盖，不会因为跳过而永久遗漏
        sql += " WHERE thread_id > :after"
        params["after"] = after
    sql += " ORDER BY thread_id LIMIT :limit"
    return [row[0] for row in db.execute(text(sql), params).all()]


def _purge_checkpoints(db, terminal_cutoff: datetime, review_cutoff: datetime) -> tuple[int, int]:
    """回收工作流检查点，返回 (终态运行的 thread 数, 超期待审批的运行数)。

    判定在内存里按 runs 行的状态做（每批只查一次库，不在循环里逐条查）：
    - **running**：绝不碰。那是活着的执行线程正在写的，删掉会让它下一个节点报错；
    - **awaiting_review**：检查点是 resume 找回中断点的唯一依据，只清超过 review_cutoff 的；
      清理时**先收尾成 failed 再删检查点**（顺序见下）；
    - **终态（success / failed / cancelled）**：超过 terminal_cutoff 的直接删；
    - **查不到运行记录**：thread_id 形如 test-<uuid> 的编辑器试运行（无运行记录），
      或运行记录已随工作流级联删除。没有任何业务状态依赖它，直接回收。

    顺序不能反（awaiting_review 分支）：先删检查点再收尾的话，中间若失败（进程被杀）会留下
    "还在等审批、但检查点已没了"的运行 —— 审批一提交就从空 state 重跑，比留着不清理危险得多。
    先收尾成 failed 之后，resume 会因"该运行不在待审核状态"被 400 拒绝，是明确且安全的失败。
    收尾走 run_service.finalize_run（05 铁律 4：运行记录只能经 create_run / finalize_run 收尾）。

    有界：每批 CHECKPOINT_BATCH 个 thread，游标推进，最多 MAX_BATCHES 批；
    每批只做 1 次 checkpoints 查询 + 1 次 runs 查询，不逐条查库。
    """
    terminal = 0
    expired_review = 0
    after: str | None = None
    for _ in range(MAX_BATCHES):
        threads = _checkpoint_threads(db, after, CHECKPOINT_BATCH)
        if not threads:
            break
        after = threads[-1]
        # thread_id 里可能是 test-<uuid> 这种非数字：只把数字的转成 id 去批量查运行记录
        ids = [int(t) for t in threads if t.isdigit()]
        runs = {r.id: r for r in db.query(Run).filter(Run.id.in_(ids)).all()} if ids else {}
        for thread in threads:
            run = runs.get(int(thread)) if thread.isdigit() else None
            if run is None:
                delete_thread_safely(thread)
                terminal += 1
                continue
            started_at = run.started_at
            if run.status == "running":
                continue
            if run.status == "awaiting_review":
                if started_at is not None and started_at < review_cutoff:
                    try:
                        run_service.finalize_run(db, run, "failed", error=AWAITING_REVIEW_EXPIRED_REASON)
                    except Exception:
                        # 单条收尾失败不中断整轮：留着它的检查点（不收尾就不删），下一轮重试
                        db.rollback()
                        logger.exception("超期待审批运行收尾失败，跳过 run_id=%s", run.id)
                        continue
                    delete_thread_safely(thread)
                    expired_review += 1
                continue
            if run.status in run_service.FINAL_STATUSES and started_at is not None and started_at < terminal_cutoff:
                delete_thread_safely(thread)
                terminal += 1
        if len(threads) < CHECKPOINT_BATCH:
            break
    else:
        logger.warning("检查点清理达到单次上限 %d 批，剩余部分留到下次", MAX_BATCHES)
    return terminal, expired_review


def purge_expired() -> dict[str, int]:
    """按配置的保留天数清理 llm_calls、audit_logs 与工作流检查点。返回各项处理条数（缺省表示没到期）。

    返回键：llm_calls / audit_logs 是删除的行数；workflow_checkpoints 是回收了检查点的 thread 数
    （终态运行 + 查不到记录的试运行）；expired_awaiting_review 是超期未审批、被一并收尾为 failed 的运行数。

    由调度器每日调用一次；也可以手工跑（脚本或运维）。异常向上抛，
    由调度器的任务包装记录失败 —— 静默失败会让表悄悄涨到撑爆磁盘。
    """
    if not settings.DATA_RETENTION_ENABLED:
        logger.info("数据保留已关闭（DATA_RETENTION_ENABLED=false），跳过清理")
        return {}

    now = datetime.now(timezone.utc)
    llm_cutoff = now - timedelta(days=settings.LLM_LOG_RETENTION_DAYS)
    audit_cutoff = now - timedelta(days=settings.AUDIT_LOG_RETENTION_DAYS)
    # 终态运行的检查点：给一个宽限期，避免与"刚收尾、正在删自己检查点"的运行抢同一份数据
    checkpoint_cutoff = now - timedelta(hours=settings.CHECKPOINT_TERMINAL_GRACE_HOURS)
    # 超期未审批的：awaiting_review 的检查点是续跑依据，只清确实没人管的
    review_cutoff = now - timedelta(days=settings.CHECKPOINT_AWAITING_REVIEW_RETENTION_DAYS)

    db = SessionLocal()
    try:
        deleted = {}
        # llm_calls 用 started_at（写入时就有值）；audit_logs 用 created_at
        removed = _purge_all(db, "llm_calls", "started_at", llm_cutoff)
        if removed:
            deleted["llm_calls"] = removed
        removed = _purge_all(db, "audit_logs", "created_at", audit_cutoff)
        if removed:
            deleted["audit_logs"] = removed
        # 检查点：计数口径是"处理过的 thread 数"，不是三张表的行数 ——
        # 一个 thread 在 checkpoints 里往往有几十上百行，报行数反而看不出回收了多少条运行。
        threads, expired = _purge_checkpoints(db, checkpoint_cutoff, review_cutoff)
        if threads:
            deleted["workflow_checkpoints"] = threads
        if expired:
            deleted["expired_awaiting_review"] = expired
        if deleted:
            logger.info(
                "数据保留清理完成：%s（llm_calls>%d 天，audit_logs>%d 天，终态运行检查点>%d 小时，超期待审批运行>%d 天）",
                deleted, settings.LLM_LOG_RETENTION_DAYS, settings.AUDIT_LOG_RETENTION_DAYS,
                settings.CHECKPOINT_TERMINAL_GRACE_HOURS, settings.CHECKPOINT_AWAITING_REVIEW_RETENTION_DAYS)
        return deleted
    finally:
        db.close()
