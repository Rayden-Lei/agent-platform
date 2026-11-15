"""数据保留：定期清理只增不减的大表（llm_calls / audit_logs）。

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
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# 单批删除条数：小一点避免长事务；配合下面的循环直到删空
BATCH_SIZE = 1000
# 单次任务最多跑多少批：防止异常情况下把调度线程占住一整晚(1000 * 200 = 20 万行/次)
MAX_BATCHES = 200


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


def purge_expired() -> dict[str, int]:
    """按配置的保留天数清理 llm_calls 与 audit_logs。返回各表删除条数（0 表示没到期的）。

    由调度器每日调用一次；也可以手工跑（脚本或运维）。异常向上抛，
    由调度器的任务包装记录失败 —— 静默失败会让表悄悄涨到撑爆磁盘。
    """
    if not settings.DATA_RETENTION_ENABLED:
        logger.info("数据保留已关闭（DATA_RETENTION_ENABLED=false），跳过清理")
        return {}

    now = datetime.now(timezone.utc)
    llm_cutoff = now - timedelta(days=settings.LLM_LOG_RETENTION_DAYS)
    audit_cutoff = now - timedelta(days=settings.AUDIT_LOG_RETENTION_DAYS)

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
        if deleted:
            logger.info("数据保留清理完成：%s（llm_calls>%d 天，audit_logs>%d 天）",
                        deleted, settings.LLM_LOG_RETENTION_DAYS, settings.AUDIT_LOG_RETENTION_DAYS)
        return deleted
    finally:
        db.close()
