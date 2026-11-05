"""迁移（docs/17 §3.3，P1 对话分类型，2026-11-05）：conversations 加 kind 与 model_id。

改什么：
  conversations  ADD kind varchar(16) NOT NULL DEFAULT 'agent'：对话类型 model / agent / workflow
  conversations  ADD model_id bigint → models ON DELETE CASCADE：模型对话直接指向模型行（kind=model 时非空）
  conversations  ADD 索引 (user_id, kind, updated_at)：对话页按类型过滤会话列表走它
  conversations  ADD 约束 ck_conversations_kind：三种类型的归属列互斥，唯一性由 DB 兜底

为什么：此前只有一种对话（绑定已发布智能体），workflow_id 一直是预留列、从未写入。
现在模型对话与工作流对话并列成为主对话类型（docs/17 §3.1），会话要能区分自己属于哪一类。

影响：kind 有默认值，旧代码写入的会话自动是 agent，行为不变；model_id 可空。
存量会话全部是智能体对话，回填 agent 即可（DEFAULT 已经生效，再显式 UPDATE 一次幂等）。
加约束前先校验存量行：有不符合三种形状的行（例如 agent_id 为空的历史脏数据）会直接报错并退出，
不会静默把约束建歪——这种情况要先人工确认那些行属于哪一类。

执行：cd backend && .venv/bin/python scripts/migrations/20261105_190000_conversation_kind.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261105_190000_conversation_kind.py --apply    # 执行

幂等：ADD COLUMN / CREATE INDEX IF NOT EXISTS；约束先查 pg_constraint 再建；重复执行无副作用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

CONSTRAINT = "ck_conversations_kind"

DDL = [
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kind varchar(16) NOT NULL DEFAULT 'agent'",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS model_id bigint REFERENCES models(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS ix_conversations_user_kind_updated ON conversations (user_id, kind, updated_at)",
]

# 存量行里不符合三种形状的：加约束会失败，先查出来让人确认
BAD_ROWS = """
    SELECT id, kind, agent_id, workflow_id, model_id FROM conversations
    WHERE NOT (
        (kind = 'agent' AND agent_id IS NOT NULL AND workflow_id IS NULL AND model_id IS NULL)
        OR (kind = 'workflow' AND workflow_id IS NOT NULL AND agent_id IS NULL AND model_id IS NULL)
        OR (kind = 'model' AND model_id IS NOT NULL AND agent_id IS NULL AND workflow_id IS NULL)
    )
    ORDER BY id LIMIT 20
"""


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        has_kind = conn.execute(text(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'kind'")).scalar()
        has_constraint = conn.execute(text("SELECT count(*) FROM pg_constraint WHERE conname = :n"), {"n": CONSTRAINT}).scalar()
        total = conn.execute(text("SELECT count(*) FROM conversations")).scalar()
        print(f"conversations：{total} 行；kind 列{'已存在' if has_kind else '待新增'}；约束{'已存在' if has_constraint else '待新增'}")
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        # kind 的 DEFAULT 已让存量行读到 agent，这里显式落一次，避免"列上默认值改了但旧行还是空"的疑虑
        conn.execute(text("UPDATE conversations SET kind = 'agent' WHERE kind IS NULL"))
        bad = conn.execute(text(BAD_ROWS)).all()
        if bad:
            print("存量里有不符合三种对话形状的行，先人工确认再建约束：")
            for row in bad:
                print("  ", tuple(row))
            raise SystemExit(1)
        if not has_constraint:
            conn.execute(text(
                "ALTER TABLE conversations ADD CONSTRAINT " + CONSTRAINT + " CHECK ("
                "(kind = 'agent' AND agent_id IS NOT NULL AND workflow_id IS NULL AND model_id IS NULL)"
                " OR (kind = 'workflow' AND workflow_id IS NOT NULL AND agent_id IS NULL AND model_id IS NULL)"
                " OR (kind = 'model' AND model_id IS NOT NULL AND agent_id IS NULL AND workflow_id IS NULL))"))
        print("已执行：kind / model_id / 索引 / 互斥约束就绪")


if __name__ == "__main__":
    main()
