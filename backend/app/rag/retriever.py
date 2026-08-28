import re

from sqlalchemy import select

from app.config import settings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.rag.embeddings import embed_query


def _extract_keywords(query: str) -> list:
    """从查询中提取关键词：英文/数字词 + 中文片段(2-gram)。"""
    keywords = set()
    for w in re.findall(r"[a-zA-Z0-9]+", query):
        if len(w) >= 2:
            keywords.add(w.lower())
    for seg in re.findall(r"[\u4e00-\u9fa5]+", query):
        if len(seg) <= 4:
            keywords.add(seg)
        else:
            for i in range(len(seg) - 1):
                keywords.add(seg[i:i + 2])
    return list(keywords)


def retrieve(kb_id: int, query: str, top_k: int = None, mode: str = "hybrid") -> list:
    """混合召回：向量相似度 + 关键词匹配，加权融合后重排。"""
    top_k = top_k or settings.RAG_TOP_K
    vec = embed_query(query)
    db = SessionLocal()
    try:
        candidates: dict = {}

        # 1. 向量召回
        dist = DocumentChunk.embedding.cosine_distance(vec)
        stmt = select(DocumentChunk, dist).where(DocumentChunk.kb_id == kb_id).order_by(dist).limit(top_k * 3)
        for chunk, distance in db.execute(stmt).all():
            vscore = 1 - float(distance)
            candidates[chunk.id] = {"chunk": chunk, "vector_score": vscore, "keyword_score": 0.0}

        # 2. 关键词召回（可选）
        if mode != "vector":
            for kw in _extract_keywords(query):
                kw_stmt = (
                    select(DocumentChunk)
                    .where(DocumentChunk.kb_id == kb_id, DocumentChunk.content.ilike(f"%{kw}%"))
                    .limit(top_k * 2)
                )
                for chunk in db.execute(kw_stmt).scalars():
                    if chunk.id not in candidates:
                        candidates[chunk.id] = {"chunk": chunk, "vector_score": 0.0, "keyword_score": 1.0}
                    else:
                        candidates[chunk.id]["keyword_score"] += 1.0

        # 3. 混合打分（向量 0.7 + 关键词 0.3）并排序
        scored = sorted(
            candidates.values(),
            key=lambda c: c["vector_score"] * 0.7 + c["keyword_score"] * 0.3,
            reverse=True,
        )[:top_k]

        results = []
        for c in scored:
            chunk = c["chunk"]
            doc = db.get(Document, chunk.doc_id)
            results.append({
                "content": chunk.content,
                "score": round(c["vector_score"] * 0.7 + c["keyword_score"] * 0.3, 4),
                "doc_id": chunk.doc_id,
                "doc_name": doc.name if doc else "",
                "meta": chunk.meta or {},
            })
        return results
    finally:
        db.close()
