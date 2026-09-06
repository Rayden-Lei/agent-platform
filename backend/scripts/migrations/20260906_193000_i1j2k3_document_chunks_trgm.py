"""迁移：document_chunks.content 建 pg_trgm GIN 索引，让关键词召回的 ILIKE '%关键词%' 走索引。

改什么：CREATE EXTENSION IF NOT EXISTS pg_trgm；CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_document_chunks_content_trgm ON document_chunks USING gin (content gin_trgm_ops)
为什么：关键词召回每个关键词一条 ILIKE 全表扫描，4 万切片时一次检索 12 个关键词要 2.5 秒，切片再涨十倍就是几十秒（2026-09-06 药品说明书导入后实测）。
  trigram 索引只对 ≥ 3 字的模式生效，配套把中文关键词从二元组改成三元组（rag/rerank.extract_keywords）。
影响：只建索引；GIN 约为文本量的 1～2 倍，写入时多一点索引维护开销。CONCURRENTLY 不阻塞读写。
执行后必做：无。
幂等：IF NOT EXISTS；中断留下的无效索引会先删再建。autocommit 连接 + lock_timeout，导入进行中拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20260906_193000_i1j2k3_document_chunks_trgm.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

INDEX = "ix_document_chunks_content_trgm"


def main() -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        invalid = conn.execute(text("SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :n AND NOT i.indisvalid"), {"n": INDEX}).scalar()
        if invalid:
            print(f"发现上次中断留下的无效索引 {INDEX}，先删除重建")
            conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}"))
        started = time.time()
        conn.execute(text(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON document_chunks USING gin (content gin_trgm_ops)"))
        size = conn.execute(text("SELECT pg_size_pretty(pg_relation_size(:n))"), {"n": INDEX}).scalar()
        print(f"trigram 索引 {INDEX} 就绪，大小 {size}，耗时 {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
