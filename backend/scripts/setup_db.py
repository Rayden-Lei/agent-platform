import os

import psycopg2

HOST = os.environ.get("PGHOST", "127.0.0.1")
PORT = int(os.environ.get("PGPORT", "5432"))
USER = os.environ.get("PGUSER", "admin")
PASSWORD = os.environ.get("PGPASSWORD", "")
DBNAME = os.environ.get("PGDATABASE", "agent_platform")

if not PASSWORD:
    print("请通过环境变量 PGPASSWORD 提供数据库密码")
    raise SystemExit(1)

# 1. 创建独立数据库（如不存在）
conn = psycopg2.connect(host=HOST, port=PORT, user=USER, password=PASSWORD, dbname="postgres")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DBNAME,))
if not cur.fetchone():
    cur.execute(f"CREATE DATABASE {DBNAME}")
    print(f"created database {DBNAME}")
conn.close()

# 2. 启用 vector 扩展
conn2 = psycopg2.connect(host=HOST, port=PORT, user=USER, password=PASSWORD, dbname=DBNAME)
conn2.autocommit = True
cur2 = conn2.cursor()
cur2.execute("CREATE EXTENSION IF NOT EXISTS vector")
cur2.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
print("vector extension version:", cur2.fetchone()[0])
conn2.close()
print("DB READY")
