"""迁移：document_chunks.embedding 建 HNSW 索引（cosine）。

改什么：CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_document_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops)
为什么：切片过万后向量召回是全表顺序扫描（4 万行 0.5 秒、40 万行数秒），`09-演进路线.md` 早已列入；2026-09-06 导入药品说明书后触发。
影响：只建索引，不改数据；CONCURRENTLY 不阻塞读写，4 万行约 1 分钟，几十万行几分钟；索引约为向量数据的 1/3 大小。
执行后必做：无。检索侧 `hnsw.ef_search` 保持默认 40；带 kb_id 过滤的查询由 pgvector 0.8 的迭代扫描兜底（见 retriever）。
幂等：IF NOT EXISTS；CONCURRENTLY 中断会留下 INVALID 索引，重跑前先 DROP INDEX（脚本会检测并处理）。
注意：CONCURRENTLY 不能在事务里跑，这里用 autocommit 连接；同样设 lock_timeout，正在导入时拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20260906_190000_f7g8h9_document_chunks_hnsw.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

INDEX = "ix_document_chunks_embedding_hnsw"


def main() -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        invalid = conn.execute(text("SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :n AND NOT i.indisvalid"), {"n": INDEX}).scalar()
        if invalid:
            print(f"发现上次中断留下的无效索引 {INDEX}，先删除重建")
            conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}"))
        started = time.time()
        conn.execute(text(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON document_chunks USING hnsw (embedding vector_cosine_ops)"))
        size = conn.execute(text("SELECT pg_size_pretty(pg_relation_size(:n))"), {"n": INDEX}).scalar()
        print(f"HNSW 索引 {INDEX} 就绪，大小 {size}，耗时 {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
