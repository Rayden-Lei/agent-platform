"""迁移：api_keys 增加入口治理字段 allowed_ips / rate_limit_per_minute。

改什么：ALTER TABLE api_keys ADD COLUMN allowed_ips jsonb NOT NULL DEFAULT '[]'；
        ALTER TABLE api_keys ADD COLUMN rate_limit_per_minute integer NOT NULL DEFAULT 0。
为什么：FR-026 API Key 级来源 IP 白名单、FR-025 单 Key 限速（12-差距补齐开发计划 1.2 步）。
  models.py 已加列，但 create_all 不会给已存在的表补列，存量库要靠本脚本。
影响：只加列并带默认值，不改数据；存量 Key 语义不变（不限制来源、用全局限速）。
执行后必做：无。
幂等：ADD COLUMN IF NOT EXISTS，重复执行无副作用。

执行：cd backend && .venv/bin/python scripts/migrations/20260905_120000_p3q4r5_api_keys_governance_fields.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS allowed_ips jsonb NOT NULL DEFAULT '[]'"))
        conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS rate_limit_per_minute integer NOT NULL DEFAULT 0"))
        print("api_keys.allowed_ips / rate_limit_per_minute 列就绪")


if __name__ == "__main__":
    main()
