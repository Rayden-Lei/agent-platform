"""迁移（2026-11-15）：回填 conversations.updated_at，让「最近活跃在前」对存量会话也成立。

改什么
------
把每条会话的 updated_at 改成「该会话最后一条消息的时间」与「原 updated_at」的较大者。
已经对的（updated_at >= 最后消息时间）不动。

为什么
------
会话列表按 updated_at 倒序排（docs/04 230 行：「按更新时间倒序」），但 2026-11-15 之前
发消息只插入 messages 行、从不 UPDATE 会话行，而 updated_at 是 TimestampMixin.onupdate
—— 只在会话行被 UPDATE 时才刷新。于是老会话继续聊不会上浮，列表退化成「创建顺序」。

代码侧已在 chat_turn.open_turn（三个对话渠道与分享访客的共同入口）补了显式刷新，
本脚本只负责把历史数据补正；不补的话，老会话要等下一次发言才会归位。

影响
----
- 只更新 conversations.updated_at 一列，不动任何业务字段。
- 没有消息的会话（刚建未发过言）保持原值。
- 执行后：无需重启（纯数据）。

执行
----
    cd backend && .venv/bin/python scripts/migrations/20261115_080000_a9m4kq_backfill_conversation_updated_at.py          # 预览
    cd backend && .venv/bin/python scripts/migrations/20261115_080000_a9m4kq_backfill_conversation_updated_at.py --apply  # 执行

幂等：条件是「updated_at < 该会话最后消息时间」，补过一次后不再满足，重复执行影响 0 行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

# 待补：会话的最后一条消息时间晚于会话自身的 updated_at
COUNT_STALE = """
SELECT count(*) FROM conversations c
JOIN (SELECT conversation_id, max(created_at) AS last_at FROM messages GROUP BY conversation_id) m
  ON m.conversation_id = c.id
WHERE m.last_at > c.updated_at
"""
SAMPLE_STALE = """
SELECT c.id, c.updated_at, m.last_at
FROM conversations c
JOIN (SELECT conversation_id, max(created_at) AS last_at FROM messages GROUP BY conversation_id) m
  ON m.conversation_id = c.id
WHERE m.last_at > c.updated_at
ORDER BY c.id LIMIT 10
"""
BACKFILL = """
UPDATE conversations c
SET updated_at = m.last_at
FROM (SELECT conversation_id, max(created_at) AS last_at FROM messages GROUP BY conversation_id) m
WHERE m.conversation_id = c.id AND m.last_at > c.updated_at
"""


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        total = conn.execute(text("SELECT count(*) FROM conversations")).scalar()
        stale = conn.execute(text(COUNT_STALE)).scalar()
        print(f"conversations：{total} 行，其中 updated_at 落后于最后一条消息的 {stale} 行")
        if stale:
            rows = conn.execute(text(SAMPLE_STALE)).all()
            print("待补样本（id, 当前 updated_at, 应为）：")
            for r in rows:
                print(f"  {r[0]}: {r[1]} -> {r[2]}")
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        result = conn.execute(text(BACKFILL))
        print(f"已执行：修正 {result.rowcount} 行 conversations.updated_at")


if __name__ == "__main__":
    main()
