"""迁移：统一向量维度为 1536。

改什么：document_chunks.embedding 由 vector(2048) 改为 vector(1536)。
为什么：models.py 曾定义 Vector(2048)，而 config.EMBEDDING_DIM=1536 且
  EMBEDDING_MODEL=text-embedding-3-small 输出 1536 维；hash 兜底也生成 1536 维。
  维度不匹配会让新文档入库直接失败（pgvector 拒绝写入 1536 维向量到 2048 维列）。

影响：删除 document_chunks 中维度 != 1536 的存量行（2048 维无法无损降维，需重新入库），
  并把受影响文档的 status 重置为 uploading、chunk_count 归 0 以便重新处理。
执行后必做：重新上传/处理受影响文档，重建其向量。

幂等：列已是 1536 维时直接跳过；重复执行无副作用。

执行：cd backend && .venv/bin/python3 scripts/migrations/20250829_153000_a1b2c3_unify_embedding_dim_1536.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

TARGET_DIM = 1536


def main() -> None:
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
        )).fetchone()
        cur_dim = (row[0] - 8) if row and row[0] and row[0] > 0 else None
        print(f"当前 embedding 列维度: {cur_dim}")
        if cur_dim == TARGET_DIM:
            print("已是 1536 维，跳过。")
            return

        affected = conn.execute(text(
            "SELECT DISTINCT doc_id FROM document_chunks WHERE vector_dims(embedding) <> :dim"
        ), {"dim": TARGET_DIM}).fetchall()

        deleted = conn.execute(text(
            "DELETE FROM document_chunks WHERE vector_dims(embedding) <> :dim"
        ), {"dim": TARGET_DIM}).rowcount
        print(f"删除维度不符的 chunk: {deleted} 行")

        if affected:
            doc_ids = [r[0] for r in affected]
            conn.execute(text(
                "UPDATE documents SET status='uploading', chunk_count=0, error=NULL WHERE id = ANY(:ids)"
            ), {"ids": doc_ids})
            print(f"重置受影响文档状态为 uploading: {doc_ids}")

        conn.execute(text(f"ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector({TARGET_DIM})"))
        print("ALTER 完成，列维度已改为 1536。")


if __name__ == "__main__":
    main()
