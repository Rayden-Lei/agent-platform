"""迁移：conversations 增加对话摘要持久化字段 summary / summary_upto_message_id / summary_updated_at。

改什么：ALTER TABLE conversations ADD COLUMN summary text；
        ALTER TABLE conversations ADD COLUMN summary_upto_message_id bigint；
        ALTER TABLE conversations ADD COLUMN summary_updated_at timestamptz。三列均可空。
为什么：FR-031 对话摘要持久化（12-差距补齐开发计划 2.1 步）。摘要与其覆盖到的消息 ID 存到会话上，
  更早消息按批增量折叠，不再每轮重新调模型。models.py 已加列，create_all 不会给已存在的表补列。
影响：只加可空列，不改数据；存量会话首次超过 CHAT_HISTORY_MAX_MESSAGES 条后按新规则生成摘要。
执行后必做：无。
幂等：ADD COLUMN IF NOT EXISTS，重复执行无副作用。

执行：cd backend && .venv/bin/python scripts/migrations/20260905_150000_s6t7u8_conversation_summary_fields.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary text"))
        conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary_upto_message_id bigint"))
        conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary_updated_at timestamptz"))
        print("conversations.summary / summary_upto_message_id / summary_updated_at 列就绪")


if __name__ == "__main__":
    main()
