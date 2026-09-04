"""迁移：api_keys.key_hash 加索引。

改什么：CREATE INDEX ix_api_keys_key_hash ON api_keys (key_hash)。
为什么：API Key 鉴权接入后每个带 Key 的请求都按 key_hash 查一次；models.py 已加 index=True，
  但 create_all 不会给已存在的表补索引，存量库要靠本脚本。
影响：只加索引，不改数据。
执行后必做：无。
幂等：IF NOT EXISTS，重复执行无副作用。

执行：cd backend && .venv/bin/python scripts/migrations/20260904_133000_k4h5i6_api_keys_key_hash_index.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash)"))
        print("api_keys.key_hash 索引就绪")


if __name__ == "__main__":
    main()
