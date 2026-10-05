"""迁移（docs/15 3.11 M2 的前半，记作 M2a）：API Key 资源作用域、会话通道与终端用户、消息幂等键。

M2 里分享相关的部分（agent_shares 表、conversations.share_id、runs.share_id）随 PB-01 另起一个脚本（M2b），
本脚本只建 PB-03 用得到的列，免得先建出没有代码读写的表。

改什么：
  api_keys       ADD agent_ids / workflow_ids / kb_ids jsonb NOT NULL DEFAULT '[]' —— Key 能调哪些智能体、工作流，检索时额外放行哪些库（D-09）
  conversations  ADD channel varchar(16) NOT NULL DEFAULT 'ui' —— ui = 登录界面里的会话，api = API Key 发起的会话
                 ADD api_key_id bigint → api_keys ON DELETE SET NULL、end_user varchar(64)（Key 背后的终端用户，调用方自己传）
                 索引 (user_id, channel, updated_at)、(api_key_id, end_user, updated_at)：两个通道各自的会话列表
  messages       ADD client_message_id varchar(64) + 部分唯一索引 (conversation_id, client_message_id) WHERE 非空 —— 调用方重试不重复落消息、不重复计费
  数据（--apply 才执行）：
  1. 已知由 API Key 发起的会话（runs.source = 'api_key' 的对话运行所在会话）改为 channel = 'api' 并补 api_key_id；
     2026-09-25 之前 Key 发起的对话运行记成了 chat，分不出来，仍按界面会话处理
  2. --disable-unscoped-keys（单独开关，默认不做）：三类作用域都为空的 Key 置为停用并列出，归属人在页面授权后再启用。
     新代码没有"作用域为空 = 全部放行"的分支，不停用它们也调不了任何资源；停用只是让页面上一眼看出"待授权"。
     会改到服务器也在用的 Key 的状态，执行前向使用者说明并确认（2026-10-05 共享库 1 个：admin 的"测试key"，从未使用）
为什么：Key 等同归属人登录，能调任意已发布智能体与工作流、能读删归属人在界面里的全部会话，同一个 Key 下所有终端用户的会话互相可见（docs/15 2.3 第 9 条、3.7.1）。
影响：只加列与索引（都有默认值或可空，旧代码照常工作）；2026-10-05 共享库 66 个会话、201 条消息、0 个 api_key 来源的对话运行。
执行后必做：无缓存要清。部署顺序：先 --apply 本脚本 → 再部署新代码（新代码要读这些列）。
幂等：ADD COLUMN / CREATE INDEX IF NOT EXISTS；回填只改 channel 仍为 ui 的会话；lock_timeout 5 秒，导入进行中拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20261005_183713_71b564_api_key_scopes_and_conversation_channel.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261005_183713_71b564_api_key_scopes_and_conversation_channel.py --apply    # 建列 + 回填会话通道
      cd backend && .venv/bin/python scripts/migrations/20261005_183713_71b564_api_key_scopes_and_conversation_channel.py --apply --disable-unscoped-keys
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import bindparam, text

from app.db.session import engine

DDL = [
    "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS agent_ids jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS workflow_ids jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS kb_ids jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS channel varchar(16) NOT NULL DEFAULT 'ui'",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS api_key_id bigint REFERENCES api_keys(id) ON DELETE SET NULL",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS end_user varchar(64)",
    "CREATE INDEX IF NOT EXISTS ix_conversations_user_channel_updated ON conversations (user_id, channel, updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_conversations_api_key_end_user_updated ON conversations (api_key_id, end_user, updated_at)",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS client_message_id varchar(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_conversation_client_message ON messages (conversation_id, client_message_id) WHERE client_message_id IS NOT NULL",
]


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"), {"t": table, "c": column}).first() is not None


def api_conversations(conn) -> list[dict]:
    """由 API Key 发起、还标着 ui 的会话（建列之前所有会话都算 ui）。一个会话取它最早那条 api_key 运行的 Key。"""
    channel_filter = " AND c.channel = 'ui'" if _column_exists(conn, "conversations", "channel") else ""
    rows = conn.execute(text(
        "SELECT DISTINCT ON (c.id) c.id, r.api_key_id FROM conversations c JOIN runs r ON r.conversation_id = c.id "
        f"WHERE r.source = 'api_key'{channel_filter} ORDER BY c.id, r.id"
    )).mappings()
    return [dict(r) for r in rows]


def unscoped_keys(conn) -> list[dict]:
    """三类作用域都为空的 Key（建列之前所有 Key 都是）。"""
    scoped = "jsonb_array_length(k.agent_ids) = 0 AND jsonb_array_length(k.workflow_ids) = 0 AND jsonb_array_length(k.kb_ids) = 0" \
        if _column_exists(conn, "api_keys", "agent_ids") else "true"
    rows = conn.execute(text(f"SELECT k.id, k.name, u.username, k.is_enabled FROM api_keys k JOIN users u ON u.id = k.user_id WHERE {scoped} ORDER BY k.id")).mappings()
    return [dict(r) for r in rows]


def main() -> None:
    apply = "--apply" in sys.argv
    disable_keys = "--disable-unscoped-keys" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        convs = api_conversations(conn)
        keys = unscoped_keys(conn)
        print("要改为 api 通道的会话：", [c["id"] for c in convs] or "无")
        print("作用域为空的 Key：", [f"{k['id']}「{k['name']}」{k['username']}{'' if k['is_enabled'] else '（已停用）'}" for k in keys] or "无",
              # 只在还有启用中的空作用域 Key 时提示；都已停用再提示会让人以为还没执行（2026-10-06 部署时看到过）
              "（加 --disable-unscoped-keys 才会停用）" if any(k["is_enabled"] for k in keys) and not disable_keys else "")
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        # 一条 UPDATE 回填（与 api_conversations 同一口径：每个会话取最早那条 api_key 运行的 Key）
        moved = conn.execute(text(
            "UPDATE conversations c SET channel = 'api', api_key_id = s.api_key_id "
            "FROM (SELECT DISTINCT ON (r.conversation_id) r.conversation_id, r.api_key_id FROM runs r "
            "      WHERE r.source = 'api_key' AND r.conversation_id IS NOT NULL ORDER BY r.conversation_id, r.id) s "
            "WHERE c.id = s.conversation_id AND c.channel = 'ui'"
        )).rowcount
        disabled = 0
        targets = [k["id"] for k in unscoped_keys(conn) if k["is_enabled"]]
        if disable_keys and targets:
            disabled = conn.execute(text("UPDATE api_keys SET is_enabled = false WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
                                    {"ids": targets}).rowcount
        print(f"已执行：建列与索引完成，{moved} 个会话改为 api 通道，停用 {disabled} 个作用域为空的 Key")


if __name__ == "__main__":
    main()
