"""迁移（docs/17 §5.2，P5 MCP 连接器，2026-11-07）：新建 mcp_servers 表，tools 加两列。

改什么：
  CREATE TABLE IF NOT EXISTS mcp_servers：外部 MCP 服务器（HTTP / SSE 传输）
  CREATE INDEX IF NOT EXISTS ix_mcp_servers_is_enabled：连接器页按"启用中"过滤
  ALTER TABLE tools ADD COLUMN IF NOT EXISTS mcp_server_id bigint：MCP 工具指向所属服务器
  ALTER TABLE tools ADD COLUMN IF NOT EXISTS remote_name varchar(128)：远端工具原名，调用时回传

为什么：MCP 的 tools 要能像普通工具一样被智能体绑定、走同一道执行闸门、进同一份审计。
方案定的是"MCP 工具 = tools 表的一行"（docs/17 §5.2），所以只需要一个服务器表和两个来源列，
不另开执行路径。mcp_server_id 不设外键：同步出来的工具与服务器生命周期解耦，
服务器删除时工具保留但停用（否则会破坏已有智能体的 tool_ids 引用）。

影响：只建新表 + 加两个可空列，存量工具 mcp_server_id 为 NULL，行为完全不变
（executor._dispatch 按 type 分发，type 仍是 builtin / http）。
新表由应用启动的 create_all 也会自动建，本脚本让"只跑迁移不启动应用"的部署路径也能建表。

执行：cd backend && .venv/bin/python scripts/migrations/20261107_100000_mcp_servers.py

幂等：CREATE TABLE / CREATE INDEX / ADD COLUMN 全部 IF NOT EXISTS，重复执行无副作用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    """
    CREATE TABLE IF NOT EXISTS mcp_servers (
        id bigserial PRIMARY KEY,
        name varchar(64) NOT NULL UNIQUE,
        description text,
        transport varchar(16) NOT NULL DEFAULT 'http',
        url varchar(512) NOT NULL,
        headers jsonb NOT NULL DEFAULT '{}',
        secret_enc text,
        is_enabled boolean NOT NULL DEFAULT true,
        allowed_hosts jsonb NOT NULL DEFAULT '[]',
        last_synced_at timestamptz,
        last_error text,
        created_by bigint REFERENCES users(id) ON DELETE SET NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_mcp_servers_is_enabled ON mcp_servers (is_enabled)",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS mcp_server_id bigint",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS remote_name varchar(128)",
    # 按服务器找它的工具是同步与详情页的主查询
    "CREATE INDEX IF NOT EXISTS ix_tools_mcp_server_id ON tools (mcp_server_id)",
]


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        has_table = conn.execute(text(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'mcp_servers'")).scalar()
        has_cols = conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'tools' AND column_name IN ('mcp_server_id', 'remote_name')")).scalar()
        tools_total = conn.execute(text("SELECT count(*) FROM tools")).scalar()
        print(f"mcp_servers 表{'已存在' if has_table else '待新建'}；"
              f"tools 的 MCP 列已存在 {has_cols}/2；现有工具 {tools_total} 个（mcp_server_id 回填为空）")
        for statement in DDL:
            conn.execute(text(statement))
        print("完成。")


if __name__ == "__main__":
    main()
