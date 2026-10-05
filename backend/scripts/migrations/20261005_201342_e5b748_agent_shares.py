"""迁移（docs/15 3.11 M2 的后半，记作 M2b，随 PB-01）：智能体分享链接。

改什么：
  agent_shares   新表：一个智能体一条分享（agent_id 唯一，FK agents CASCADE）；code 唯一；访问方式 public / login、访问密码哈希、
                 有效期、token_version（改密码 / 改访问方式 / 重置链接时 +1）、三个限额（显式范围，不用 0 表示不限）、
                 是否允许 HTTP 工具、是否显示引用；created_by → users RESTRICT（公开访客的会话与运行记在创建者名下）、updated_by → users SET NULL
  conversations  ADD share_id bigint → agent_shares ON DELETE CASCADE + 索引 (share_id, end_user, updated_at)：访客会话（channel=share）
  runs           ADD share_id bigint → agent_shares ON DELETE SET NULL + 索引 (share_id, started_at)：访客运行（source=share），每日总量按它计数
为什么：分享体验链接（点名第 1 条）——此前除登录与健康检查外都要 JWT 或 API Key，没有任何公开访问能力。
影响：只建新表与可空列，旧代码照常工作；没有数据要改。
执行后必做：无缓存要清。部署顺序：先 --apply 本脚本 → 再部署新代码。本机先起新代码时 create_all 会自动建出 agent_shares，
  本脚本用 IF NOT EXISTS 兼容；share_id 两列 create_all 不会加，必须跑本脚本。
幂等：CREATE TABLE / ADD COLUMN / CREATE INDEX IF NOT EXISTS；lock_timeout 5 秒，导入进行中拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20261005_201342_e5b748_agent_shares.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261005_201342_e5b748_agent_shares.py --apply    # 执行
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    """CREATE TABLE IF NOT EXISTS agent_shares (
        id bigserial PRIMARY KEY,
        agent_id bigint NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
        code varchar(32) NOT NULL UNIQUE,
        is_enabled boolean NOT NULL DEFAULT false,
        access_mode varchar(16) NOT NULL DEFAULT 'public',
        password_hash varchar(128),
        expires_at timestamptz,
        token_version integer NOT NULL DEFAULT 0,
        rate_limit_per_minute integer NOT NULL DEFAULT 20,
        daily_message_limit integer NOT NULL DEFAULT 1000,
        visitor_daily_limit integer NOT NULL DEFAULT 50,
        allow_http_tools boolean NOT NULL DEFAULT false,
        show_citations boolean NOT NULL DEFAULT true,
        created_by bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        updated_by bigint REFERENCES users(id) ON DELETE SET NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )""",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS share_id bigint REFERENCES agent_shares(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS ix_conversations_share_end_user_updated ON conversations (share_id, end_user, updated_at)",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS share_id bigint REFERENCES agent_shares(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_runs_share_started_at ON runs (share_id, started_at)",
]


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        exists = conn.execute(text("SELECT to_regclass('agent_shares')")).scalar() is not None
        print("agent_shares：", "已存在" if exists else "待新建", "；conversations / runs 加 share_id；没有数据要改")
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        print("已执行：agent_shares 与两列 share_id 就绪")


if __name__ == "__main__":
    main()
