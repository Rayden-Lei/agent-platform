"""迁移：documents 增加续处理所需的 processing_node / heartbeat_at / resume_offset。

改什么：
  ALTER TABLE documents ADD COLUMN processing_node varchar(128)；   -- 负责处理的节点（主机名）：共享库多个后端时只续本机的
  ALTER TABLE documents ADD COLUMN heartbeat_at timestamptz；       -- 每批提交时刷新；长时间不动视为中断（页面"疑似中断"、可续处理）
  ALTER TABLE documents ADD COLUMN resume_offset integer NOT NULL DEFAULT 0；  -- 本次处理从第几片接着做，前端据此算速度
为什么：几个小时的导入中途后端被杀 / 向量服务断了只能整篇重来（2026-09-06 使用者要求"中断后继续"）。
影响：只加可空列 / 带默认值的列；不回填。
执行后必做：重启后端。
幂等：ADD COLUMN IF NOT EXISTS；lock_timeout 5 秒，导入进行中拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20260906_200000_l4m5n6_documents_resume.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_node varchar(128)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS resume_offset integer NOT NULL DEFAULT 0",
]


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        for statement in DDL:
            conn.execute(text(statement))
        print("documents 续处理列就绪")


if __name__ == "__main__":
    main()
