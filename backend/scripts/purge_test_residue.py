"""手工回收 pytest 残留：清掉所有以 pytest- 开头、且创建于指定时刻之前的行。

为什么需要这个脚本
------------------
tests/conftest.py 的 pytest_sessionfinish 只在**会话正常结束**时回收，起点是"本次会话开始"。
两个漏洞：
  1. 进程被 kill（Ctrl-C 两次、OOM、超时 kill）时 sessionfinish 根本不执行；
  2. 即使执行，时间窗只覆盖本次会话，之前会话漏下的永远清不到。
2026-11-15 的现场就是这样：本机两次 kill 掉全量测试，留下 2 个 pytest-share-kb-* 知识库、
17 个 pytest-embed-* 向量模型、110 个 11-08 的 pytest-mcp-bulk-* 工具，
知识库列表页直接把它们显示给了使用者。

所以回收必须有一个**不依赖测试生命周期**的入口。

时间窗方向（这是最容易写错的地方）
--------------------------------
tests/cleanup.purge_test_rows(since) 的判据是 created_at >= since，即"清掉 since 之后创建的"
—— 那是给"会话结束时清理本次运行"用的。本脚本要清的是"之前历史上漏下的"；
若直接复用同一个 since 参数，方向正好相反，一条都匹配不到却会静默报告"没有残留"
（2026-11-15 第一版就踩了，实测残留 created_at=14:39 而脚本报"无残留"）。

因此这里不复用 purge_test_rows 的时间窗，改为自己按 created_at < cutoff 删除；
但**复用同一份 _DELETE_ORDER 与级联顺序**，不引入第二套口径。

执行
----
    cd backend && .venv/bin/python scripts/purge_test_residue.py              # 预览
    cd backend && .venv/bin/python scripts/purge_test_residue.py --apply    # 执行
    cd backend && .venv/bin/python scripts/purge_test_residue.py --hours 24 # 只清 24 小时前的

幂等：删过之后同一条件不再命中，重复执行影响 0 行。
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from tests.cleanup import _DELETE_ORDER, TEST_PREFIX


def _cutoff(hours: float) -> datetime:
    """早于这个时刻的行算残留。用绝对时刻（带 tz），避免与库里的 timestamptz 比较时差 8 小时。"""
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _count(db, cutoff: datetime) -> list:
    """只统计不删除。判据与删除严格一致：pytest- 前缀 且 created_at < cutoff。"""
    found = []
    params = {"prefix": TEST_PREFIX + "%", "cutoff": cutoff}
    for table, column in _DELETE_ORDER:
        try:
            n = db.execute(
                text(f'select count(*) from "{table}" where "{column}" like :prefix and created_at < :cutoff'),
                params,
            ).scalar()
        except Exception as exc:  # noqa: BLE001 表/列在存量库可能不存在，跳过并说明
            print(f"  跳过 {table}：{type(exc).__name__}")
            continue
        if n:
            found.append((table, int(n)))
    return found


def _purge(db, cutoff: datetime) -> dict:
    """按 _DELETE_ORDER 逐表删（子表在前、父表在后），被真实数据引用的行跳过不删。"""
    deleted = {}
    skipped = 0
    params = {"prefix": TEST_PREFIX + "%", "cutoff": cutoff}
    for table, column in _DELETE_ORDER:
        try:
            ids = [r[0] for r in db.execute(
                text(f'select id from "{table}" where "{column}" like :prefix and created_at < :cutoff'),
                params,
            ).all()]
        except Exception:
            continue
        removed = 0
        for row_id in ids:
            savepoint = db.begin_nested()
            try:
                result = db.execute(text(f'delete from "{table}" where id = :id'), {"id": row_id})
                removed += result.rowcount
            except IntegrityError:
                # 仍被非测试数据引用（RESTRICT）：保留，否则会打断真实数据的外键
                savepoint.rollback()
                skipped += 1
                continue
            savepoint.commit()
        if removed:
            deleted[table] = removed
    if skipped:
        deleted["_skipped"] = skipped
    return deleted


def _purge_llm_calls(db, cutoff: datetime) -> int:
    """调用日志没有 name 列，按 model_name 前缀清。"""
    r = db.execute(
        text("delete from llm_calls where started_at < :cutoff and model_name like :prefix"),
        {"cutoff": cutoff, "prefix": TEST_PREFIX + "%"},
    )
    return int(r.rowcount or 0)


def _purge_checkpoint_threads(db) -> int:
    """回收 run 记录已不存在的 checkpoint thread（引擎直跑的用例留下的）。

    不按时间窗：checkpoint 表没有 created_at，判据是"还对应得上一份运行记录吗"。
    """
    rows = db.execute(text(
        "SELECT DISTINCT thread_id FROM checkpoints "
        "WHERE NOT EXISTS (SELECT 1 FROM runs r WHERE r.id::text = checkpoints.thread_id)"
    )).all()
    threads = [r[0] for r in rows]
    if not threads:
        return 0
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        db.execute(text(f"DELETE FROM {table} WHERE thread_id = ANY(:t)"), {"t": threads})
    return len(threads)


def main() -> int:
    ap = argparse.ArgumentParser(description="回收 pytest- 前缀的测试残留")
    ap.add_argument("--apply", action="store_true", help="真正删除；不加只预览")
    ap.add_argument("--hours", type=float, default=0,
                    help="只清这么多小时之前创建的（默认 0 = 全部历史残留）")
    args = ap.parse_args()

    cutoff = _cutoff(args.hours)
    db = SessionLocal()
    try:
        found = _count(db, cutoff)
        if not found:
            print(f"没有找到 {TEST_PREFIX}* 残留（创建时间早于 {cutoff:%Y-%m-%d %H:%M} UTC）")
            return 0
        print(f"找到 {TEST_PREFIX}* 残留（创建时间早于 {cutoff:%Y-%m-%d %H:%M} UTC）：")
        for table, n in found:
            print(f"  {table}: {n}")

        if not args.apply:
            print("以上为预览，未删除；确认后加 --apply")
            return 0

        deleted = _purge(db, cutoff)
        llm = _purge_llm_calls(db, cutoff)
        if llm:
            deleted["llm_calls"] = llm
        threads = _purge_checkpoint_threads(db)
        if threads:
            deleted["checkpoint_threads"] = threads
        db.commit()
        if deleted:
            print("已删除：" + "、".join(f"{t} {n}" for t, n in deleted.items()))
        else:
            print("没有可删除的行")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
