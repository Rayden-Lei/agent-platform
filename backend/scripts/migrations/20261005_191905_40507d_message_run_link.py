"""迁移（docs/15 3.7.1 的幂等，随 PB-03）：消息记下所属的运行记录。

改什么：
  messages  ADD run_id bigint → runs ON DELETE SET NULL + 索引 ix_messages_run_id —— 一轮对话的用户消息与回答都记下这一轮的运行记录
为什么：调用方带 client_message_id 重试时要"返回首次的结果"——首次的回答全文、message_id、run_id 与状态（完成 / 失败 / 仍在生成）。
  此前消息与运行记录之间没有关联，只能按时间或内容去猜，同一会话里有并发或重复内容时会对错。
影响：只加一个可空列与索引，旧代码照常工作；存量消息的 run_id 为空（只有带 client_message_id 的新消息会被回放，不需要回填）。
执行后必做：无缓存要清。部署顺序：先 --apply 本脚本 → 再部署新代码（新代码要读写这一列）。
幂等：ADD COLUMN / CREATE INDEX IF NOT EXISTS；lock_timeout 5 秒，导入进行中拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20261005_191905_40507d_message_run_link.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261005_191905_40507d_message_run_link.py --apply    # 执行
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS run_id bigint REFERENCES runs(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_messages_run_id ON messages (run_id)",
]


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        exists = conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = 'messages' AND column_name = 'run_id'")).first() is not None
        print("messages.run_id：", "已存在" if exists else "待新建", "；没有数据要改")
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        print("已执行：messages.run_id 与索引就绪")


if __name__ == "__main__":
    main()
