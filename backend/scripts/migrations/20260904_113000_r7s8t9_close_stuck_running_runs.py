"""数据修复：关闭历史遗留、永远停留在 running 的运行记录。

改什么：runs 表中 status='running' 且 started_at IS NULL 的行。
为什么：修复前所有入口都不写 started_at；定时任务未传 thread_id 每次执行前抛错并被吞掉，
  对话被客户端中断、上下文构建失败时也不收尾，累计上千条永远 running 的记录，污染监控统计。
  修复后（run_service.create_run）所有新记录都带 started_at，因此 "started_at IS NULL" 能精确
  圈出历史遗留行，不会误伤正在执行的新记录。
影响：
  - 默认模式：把这些行置为 failed，error 写明原因，finished_at 保持空（真实结束时间未知）。
  - --delete-scheduled：额外把其中定时任务产生的行（input.scheduled = true）直接删除，
    它们是同一条 bug 每 5 分钟制造的重复噪音，没有保留价值；run_nodes 由外键 CASCADE 级联删除。
执行后必做：无（运行记录页无缓存）。
幂等：不带 --apply 只预览行数；处理过的行不再满足条件，重复执行无副作用。

执行：cd backend && .venv/bin/python scripts/migrations/20260904_113000_r7s8t9_close_stuck_running_runs.py [--apply] [--delete-scheduled]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

STUCK = "status = 'running' AND started_at IS NULL"
SCHEDULED = "(input->>'scheduled') = 'true'"
REASON = "历史遗留：收尾逻辑缺失导致长期停留在 running，2026-09-04 由迁移脚本统一关闭"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际执行；不带则只预览")
    parser.add_argument("--delete-scheduled", action="store_true", help="定时任务产生的遗留行直接删除而非置为 failed")
    args = parser.parse_args()

    with engine.begin() as conn:
        rows = conn.execute(text(
            f"SELECT run_type, {SCHEDULED} AS scheduled, count(*) FROM runs WHERE {STUCK} GROUP BY 1, 2 ORDER BY 1, 2"
        )).fetchall()
        total = sum(r[2] for r in rows)
        print(f"待处理（running 且无 started_at）共 {total} 行：")
        for run_type, scheduled, cnt in rows:
            print(f"  run_type={run_type:9s} scheduled={str(scheduled):5s} {cnt} 行")
        if not args.apply:
            print("预览模式，未做任何改动。加 --apply 执行。")
            return
        if total == 0:
            print("无需处理。")
            return

        if args.delete_scheduled:
            deleted = conn.execute(text(f"DELETE FROM runs WHERE {STUCK} AND {SCHEDULED}")).rowcount
            print(f"已删除定时任务遗留行: {deleted}")
        updated = conn.execute(text(
            f"UPDATE runs SET status = 'failed', error = :reason WHERE {STUCK}"
        ), {"reason": REASON}).rowcount
        print(f"已置为 failed: {updated}")


if __name__ == "__main__":
    main()
