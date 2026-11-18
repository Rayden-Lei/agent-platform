"""迁移（docs/15 PB-11，2026-11-18）：API Key 有效期与配额语义纠正。

改什么
------
1. api_keys ADD expires_at timestamptz（可空）—— NULL = 永不过期；到期后鉴权直接 401「已过期」且不扣配额。
   加部分索引 (expires_at) WHERE expires_at IS NOT NULL：清理/巡检按到期时间扫，不会扫到永不过期的行。
2. api_keys.quota 改为可空 —— NULL = 不限次数，0 = 一次都不能调（沿用旧语义）。
   旧代码是 NOT NULL + 扣减条件 `used < quota`，页面把 0 显示成"不限"，实际 0 次都调不了（docs/15 2.3 第 28 条）。

为什么
------
- 现在没有有效期，泄漏的 Key 只能删了重建，重建又必然换明文、调用方要改配置；
  轮换接口（POST /api-keys/{id}/rotate）只换明文、其余设置不变，前提是"到期自动失效"这条路能走通。
- 配额一个值两种含义是最容易踩的坑：表单写 0 = 不限，服务端 0 = 全拒。改成"NULL 表示不限、0 表示全拒"，
  一次切换，前后端同批（docs/04 4.12 已同批改）。

影响
----
- 只加一列一索引 + 放开一个 NOT NULL 约束，不动任何数据：存量 quota 全部非空，放约束不影响它们；
  存量 expires_at 全为 NULL（永不过期），行为与迁移前完全一致。
- 放开 NOT NULL 是纯放宽：旧代码读到 NULL 只会在 `used < quota` 里恒为 NULL（被当成不满足），
  但旧代码里没有写 NULL 的路径，所以旧代码在新库上行为不变。
- 部署顺序：先 --apply 本脚本 → 再部署新代码（新代码要读 expires_at，并在 quota 为 NULL 时放行）。

执行后必做
----------
- 无缓存要清。
- 想让已有 Key 有过期时间：用 PUT /api-keys/{id} 或 POST /api-keys/{id}/rotate 带 expires_at 逐条设置，本脚本不猜。

幂等
----
ADD COLUMN IF NOT EXISTS / DROP NOT NULL 本身幂等（DROP NOT NULL 对已可空的列是空操作）；
CREATE INDEX IF NOT EXISTS；重复执行第二次 0 行变更。

执行：cd backend && .venv/bin/python scripts/migrations/20261118_120000_k3f7wa_api_key_expires_at.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261118_120000_k3f7wa_api_key_expires_at.py --apply    # 建列 + 放开 quota 约束
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS expires_at timestamp with time zone",
    "CREATE INDEX IF NOT EXISTS ix_api_keys_expires_at ON api_keys (expires_at) WHERE expires_at IS NOT NULL",
    "ALTER TABLE api_keys ALTER COLUMN quota DROP NOT NULL",
]


def _column(conn, column: str) -> dict | None:
    row = conn.execute(text(
        "SELECT is_nullable, data_type FROM information_schema.columns WHERE table_name = 'api_keys' AND column_name = :c"
    ), {"c": column}).mappings().first()
    return dict(row) if row else None


def _expiring(conn) -> list[dict]:
    """已有过期时间的 Key（存量全为 NULL，正常情况下是空列表）。"""
    rows = conn.execute(text(
        "SELECT k.id, k.name, u.username, k.expires_at FROM api_keys k JOIN users u ON u.id = k.user_id "
        "WHERE k.expires_at IS NOT NULL ORDER BY k.expires_at, k.id"
    )).mappings()
    return [dict(r) for r in rows]


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        expires = _column(conn, "expires_at")
        quota = _column(conn, "quota")
        total = conn.execute(text("SELECT count(*) FROM api_keys")).scalar()
        expiring = _expiring(conn) if expires else []
        print(f"api_keys 共 {total} 行；expires_at 列：{expires or '不存在'}；quota 列：{quota or '不存在'}")
        print("已设有效期的 Key：", [f"{k['id']}「{k['name']}」{k['username']} → {k['expires_at']}" for k in expiring] or "无")
        if not apply:
            print("预览：将执行")
            for statement in DDL:
                print(f"  {statement}")
            print("确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        print("已执行：expires_at 列、部分索引、quota 可空（NULL = 不限）")


if __name__ == "__main__":
    main()
