"""迁移：新建 system_settings 表（运行时可调参数，页面"导入设置"）。

改什么：
  CREATE TABLE system_settings (key varchar(64) PK, value jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), updated_by varchar(64))
为什么：导入流水线的并发请求数 / 写库缓冲 / 批大小 / 每次请求条数要能在页面上调，不能每改一次就改 .env 重启
      （2026-09-06 使用者要求"搞成可以配置的，在页面上"）。规格与默认值在 services/settings_service.SPECS。
影响：只建新表，不动存量数据；应用启动的 create_all 也会自动建，这里是备案 + 手工部署用。
执行后必做：无（后端读值不缓存）。
幂等：CREATE TABLE IF NOT EXISTS；lock_timeout 5 秒。

执行：cd backend && .venv/bin/python scripts/migrations/20260906_213000_o7p8q9_system_settings.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    """CREATE TABLE IF NOT EXISTS system_settings (
        key varchar(64) PRIMARY KEY,
        value jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by varchar(64)
    )""",
]


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        for statement in DDL:
            conn.execute(text(statement))
        print("system_settings 表就绪")


if __name__ == "__main__":
    main()
