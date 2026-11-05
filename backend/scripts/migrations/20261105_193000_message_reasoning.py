"""迁移：messages 增加 reasoning 列（模型思维链全文，可空 text）。

改什么：ALTER TABLE messages ADD COLUMN reasoning text。
为什么：思考过程此前只随 SSE 推给前端、不落库，刷新或切回会话后"思考过程"就消失
  （2026-11-05 使用者反馈"思考过程怎么也没了"）。落库后历史接口返回，前端回放折叠行。
影响：只加可空列，不改数据；存量消息 reasoning 为空，前端不显示思考行，与旧行为一致。
执行后必做：无。
幂等：ADD COLUMN IF NOT EXISTS，重复执行无副作用。

执行：cd backend && .venv/bin/python scripts/migrations/20261105_193000_message_reasoning.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS reasoning text"))
        print("messages.reasoning 列就绪")


if __name__ == "__main__":
    main()
