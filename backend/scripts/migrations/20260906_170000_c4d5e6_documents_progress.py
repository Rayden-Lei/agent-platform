"""迁移：documents 增加处理进度列 chunk_total / processing_started_at / finished_at。

改什么：
  ALTER TABLE documents ADD COLUMN chunk_total integer；          -- 分片后确定的计划切片总数，处理中据此算百分比
  ALTER TABLE documents ADD COLUMN processing_started_at timestamptz；-- 开始向量化入库的时间，据此算速度与预计剩余
  ALTER TABLE documents ADD COLUMN finished_at timestamptz；       -- ready / failed 的时间，据此算总耗时
  回填：已是 ready / failed 的文档 chunk_total = chunk_count（历史文档没有起止时间，保持 NULL）。
为什么：导入十万行表格时前端只能看到 chunk_count 在涨，不知道总数、速度和还要多久（2026-09-06 使用者要求）。
影响：只加可空列；回填只写 chunk_total 为空的终态行，重复执行为 0 行。
执行后必做：重启后端（模型多了三列）。
幂等：ADD COLUMN IF NOT EXISTS；回填带 IS NULL 条件。

执行：cd backend && .venv/bin/python scripts/migrations/20260906_170000_c4d5e6_documents_progress.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_total integer",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_started_at timestamptz",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS finished_at timestamptz",
]
BACKFILL = "UPDATE documents SET chunk_total = chunk_count WHERE chunk_total IS NULL AND status IN ('ready', 'failed')"


def main() -> None:
    with engine.begin() as conn:
        # DDL 要抢 ACCESS EXCLUSIVE 锁：正在导入的文档每十几秒才提交一次，排队等锁期间所有查 documents 的请求都会被堵在后面
        # （2026-09-06 实测把页面堵成 500 十几分钟）。设 lock_timeout 拿不到锁就报错退出，等导入结束再跑。
        conn.execute(text("SET lock_timeout = '5s'"))
        for statement in DDL:
            conn.execute(text(statement))
        filled = conn.execute(text(BACKFILL)).rowcount
        print(f"documents 进度列就绪；回填 chunk_total {filled} 行")


if __name__ == "__main__":
    main()
