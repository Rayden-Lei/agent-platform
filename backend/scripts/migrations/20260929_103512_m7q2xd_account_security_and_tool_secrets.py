"""迁移（docs/15 3.11 M0）：账号安全与工具凭据托管的表结构，以及存量工具请求头里的凭据搬家。

改什么：
  users  ADD token_version integer NOT NULL DEFAULT 0 —— JWT 里带 ver，重置密码 / 停用 / 改密 / 退出其他设备时 +1，旧令牌即失效（OP-04）
         ADD must_change_password boolean NOT NULL DEFAULT false —— 为真时除 /auth/me 与改密外全部 403（OP-04）
         ADD display_name varchar(64)、email varchar(128)、phone varchar(32)、password_changed_at、last_login_at（个人中心，OP-03）
  tools  ADD auth jsonb NOT NULL DEFAULT '{}' —— 鉴权方式 {type: api_key / bearer / basic, location, name}，不含密钥（RS-06）
         ADD secret_enc text —— 加密后的凭据，与模型密钥同一套 encrypt_secret；任何接口不回传
         ADD created_by bigint → users ON DELETE SET NULL、updated_at timestamptz NOT NULL DEFAULT now()
  数据（--apply 才执行）：
  1. 工具 config.headers 里疑似凭据的键（名字含 authorization / cookie / token / key / secret）搬进 secret_enc：
     Authorization: Bearer xxx → bearer；其余 → api_key（位置 header、参数名为原键名）。一个工具有多个疑似键时不自动处理，列出来人工改
  2. --flag-default-admins（单独开关，默认不做）：仍在用内置默认口令的管理员置 must_change_password。
     这一步会让该管理员在新后端上除改密外全部 403、用它登录的 pytest 全部失败，必须和使用者约好：
     先在页面上改掉口令并更新 backend/.env 的 TEST_ADMIN_PASSWORD，这一步就成了 0 行（改过口令的不会被标记）
为什么：工具请求头里的第三方 Token 原样存、原样返回给所有 admin / developer（docs/15 2.3 第 13 条）；
  重置密码不吊销旧令牌、默认口令不强制修改（第 26 条）。
影响：只加列（都有默认值或可空，旧代码照常工作）；2026-09-29 共享库预期：0 个工具带疑似凭据的请求头，1 个管理员仍用默认口令（只比对哈希，不打印口令）。
执行后必做：无缓存要清。部署顺序：先 --apply 本脚本 → 再部署新代码（新代码要读这些列）。
幂等：ADD COLUMN IF NOT EXISTS；搬家只处理 headers 里还有疑似键、且 secret_enc 为空的工具；lock_timeout 5 秒，拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20260929_103512_m7q2xd_account_security_and_tool_secrets.py                        # 预览
      cd backend && .venv/bin/python scripts/migrations/20260929_103512_m7q2xd_account_security_and_tool_secrets.py --apply                # 建列 + 凭据搬家
      cd backend && .venv/bin/python scripts/migrations/20260929_103512_m7q2xd_account_security_and_tool_secrets.py --apply --flag-default-admins
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import bindparam, text

from app.core.security import encrypt_secret, verify_password
from app.db.session import engine

DDL = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version integer NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name varchar(64)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email varchar(128)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone varchar(32)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at timestamptz",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at timestamptz",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS auth jsonb NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS secret_enc text",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS created_by bigint REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()",
]
# 与 tool_service.SECRET_HEADER_MARKERS 同一口径：请求头键名含这些词就当作凭据
SECRET_HEADER_MARKERS = ("authorization", "cookie", "token", "key", "secret")
DEFAULT_ADMIN_PASSWORD = "admin123"  # 仓库公开的内置默认口令（main.py 空库初始化用），只用来比对哈希


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"), {"t": table, "c": column}).first() is not None


def _secret_keys(headers: dict) -> list[str]:
    return [k for k in (headers or {}) if any(m in k.lower() for m in SECRET_HEADER_MARKERS)]


def plan_tool_secrets(conn, tool_ids: list[int] | None = None) -> list[dict]:
    """要搬家的工具：headers 里有且只有一个疑似凭据键、还没有 secret_enc。多个疑似键的记为 manual，不自动处理。"""
    has_secret = _column_exists(conn, "tools", "secret_enc")
    where = " AND id IN :ids" if tool_ids is not None else ""
    stmt = text(f"SELECT id, name, config{', secret_enc' if has_secret else ', NULL AS secret_enc'} FROM tools WHERE config ? 'headers'{where} ORDER BY id")
    if tool_ids is not None:
        stmt = stmt.bindparams(bindparam("ids", expanding=True))
    plans = []
    for row in conn.execute(stmt, {"ids": list(tool_ids)} if tool_ids is not None else {}).mappings():
        headers = (row["config"] or {}).get("headers") or {}
        keys = _secret_keys(headers)
        if not keys or row["secret_enc"]:
            continue
        if len(keys) > 1:
            plans.append({"tool_id": row["id"], "name": row["name"], "action": "manual", "keys": keys})
            continue
        key, value = keys[0], str(headers[keys[0]])
        bearer = key.lower() == "authorization" and value.lower().startswith("bearer ")
        auth = {"type": "bearer"} if bearer else {"type": "api_key", "location": "header", "name": key}
        plans.append({"tool_id": row["id"], "name": row["name"], "action": "move", "keys": keys, "auth": auth,
                      "secret": value[7:].strip() if bearer else value, "headers": {k: v for k, v in headers.items() if k != key}})
    return plans


def apply_tool_secrets(conn, plans: list[dict]) -> int:
    moved = 0
    for p in plans:
        if p["action"] != "move":
            continue
        conn.execute(
            text("UPDATE tools SET auth = CAST(:a AS jsonb), secret_enc = :s, config = jsonb_set(config, '{headers}', CAST(:h AS jsonb)), updated_at = now() WHERE id = :id"),
            {"a": json.dumps(p["auth"]), "s": encrypt_secret(p["secret"]), "h": json.dumps(p["headers"], ensure_ascii=False), "id": p["tool_id"]},
        )
        moved += 1
    return moved


def default_password_admins(conn) -> list[dict]:
    """仍在用内置默认口令的启用中管理员（bcrypt 比对，不打印口令）。"""
    rows = conn.execute(text("SELECT id, username, password_hash FROM users WHERE role = 'admin' AND is_active")).mappings()
    return [{"id": r["id"], "username": r["username"]} for r in rows if verify_password(DEFAULT_ADMIN_PASSWORD, r["password_hash"])]


def main() -> None:
    apply = "--apply" in sys.argv
    flag_admins = "--flag-default-admins" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        plans = plan_tool_secrets(conn)
        admins = default_password_admins(conn)
        for p in plans:
            if p["action"] == "move":
                print(f"工具 {p['tool_id']}「{p['name']}」：请求头 {p['keys'][0]} 搬进托管凭据（{p['auth']['type']}）")
            else:
                print(f"工具 {p['tool_id']}「{p['name']}」：请求头里有多个疑似凭据 {p['keys']}，不自动处理，请在工具页改用鉴权配置")
        print("工具凭据：", "没有需要搬的" if not plans else f"{len(plans)} 个")
        print("仍用默认口令的管理员：", [a["username"] for a in admins] or "无",
              "（加 --flag-default-admins 才会置为必须改密）" if admins and not flag_admins else "")
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        moved = apply_tool_secrets(conn, plan_tool_secrets(conn))
        flagged = 0
        if flag_admins and admins:
            flagged = conn.execute(text("UPDATE users SET must_change_password = true WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
                                   {"ids": [a["id"] for a in admins]}).rowcount
        print(f"已执行：建列完成，工具凭据搬家 {moved} 个，标记必须改密 {flagged} 个管理员")


if __name__ == "__main__":
    main()
