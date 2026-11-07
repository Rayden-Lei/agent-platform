"""迁移（2026-11-08）：runs 加 (status, started_at) 复合索引。

改什么：
  CREATE INDEX IF NOT EXISTS ix_runs_status_started_at ON runs (status, started_at)

为什么：工作台概览里的「卡住的运行」是
    WHERE status = 'running' AND started_at < now() - interval '1 hour'
而「今天失败数」是 WHERE status = 'failed' AND started_at >= <今日零点>，
两者都只用到单列索引（status 或 started_at），另一条条件退化成逐行过滤。
runs 到百万行后这是一次大范围扫描，而它挂在每次打开工作台的请求上。

复合索引让"状态 + 时间窗"一次定位。status 在前：等值条件的选择性比范围条件好，
PostgreSQL 能先用它把候选集缩到 running / failed 那几行，再按时间切。

影响：只加索引，不改数据与查询。索引本身约 (状态数 × 时间) 量级的存储，可以接受。

执行：cd backend && .venv/bin/python scripts/migrations/20261108_120000_runs_status_index.py

幂等：IF NOT EXISTS，重复执行无副作用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    "CREATE INDEX IF NOT EXISTS ix_runs_status_started_at ON runs (status, started_at)",
]


def main() -> None:
    with engine.begin() as conn:
        for statement in DDL:
            conn.execute(text(statement))
    print(f"runs 复合索引就绪（执行 {len(DDL)} 条 DDL）")


if __name__ == "__main__":
    main()
