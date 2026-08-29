from sqlalchemy import select

from app.config import settings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.rag.embeddings import embed_query
from app.rag.rerank import extract_keywords, rerank


def _collect_candidates(db, kb_id: int, query: str, top_k: int, mode: str) -> list:
    """召回候选池：向量相似度 + 关键词匹配，计算混合分（向量 0.7 + 关键词 0.3）。"""
    vec = embed_query(query)
    candidates: dict = {}

    # 1. 向量召回
    dist = DocumentChunk.embedding.cosine_distance(vec)
    stmt = select(DocumentChunk, dist).where(DocumentChunk.kb_id == kb_id).order_by(dist).limit(top_k * 3)
    for chunk, distance in db.execute(stmt).all():
        vscore = 1 - float(distance)
        candidates[chunk.id] = {
            "chunk": chunk,
            "content": chunk.content,
            "vector_score": vscore,
            "keyword_score": 0.0,
        }

    # 2. 关键词召回（可选）
    if mode != "vector":
        for kw in extract_keywords(query):
            kw_stmt = (
                select(DocumentChunk)
                .where(DocumentChunk.kb_id == kb_id, DocumentChunk.content.ilike(f"%{kw}%"))
                .limit(top_k * 2)
            )
            for chunk in db.execute(kw_stmt).scalars():
                if chunk.id not in candidates:
                    candidates[chunk.id] = {
                        "chunk": chunk,
                        "content": chunk.content,
                        "vector_score": 0.0,
                        "keyword_score": 1.0,
                    }
                else:
                    candidates[chunk.id]["keyword_score"] += 1.0

    # 3. 混合打分
    for c in candidates.values():
        c["score"] = c["vector_score"] * 0.7 + c["keyword_score"] * 0.3
    return list(candidates.values())


def _format_items(db, ranked: list, top_k: int, enriched: bool = False) -> list:
    items = []
    for c in ranked[:top_k]:
        chunk = c["chunk"]
        doc = db.get(Document, chunk.doc_id)
        item = {
            "content": chunk.content,
            "score": c["score"],
            "doc_id": chunk.doc_id,
            "doc_name": doc.name if doc else "",
            "meta": chunk.meta or {},
        }
        if enriched:
            item["vector_score"] = round(c.get("vector_score", 0.0), 4)
            item["keyword_score"] = round(c.get("keyword_score", 0.0), 4)
            item["matched_keywords"] = c.get("matched_keywords", [])
        items.append(item)
    return items


def retrieve(kb_id: int, query: str, top_k: int = None, mode: str = "hybrid") -> list:
    """混合召回 + 重排，返回与旧版兼容的结果（content/score/doc_id/doc_name/meta）。"""
    top_k = top_k or settings.RAG_TOP_K
    db = SessionLocal()
    try:
        candidates = _collect_candidates(db, kb_id, query, top_k, mode)
        ranked = rerank(query, candidates)
        return _format_items(db, ranked, top_k, enriched=False)
    finally:
        db.close()


def retrieve_with_stats(kb_id: int, query: str, top_k: int = None, mode: str = "hybrid") -> dict:
    """检索 + 召回质量统计，供评测/调试接口使用。"""
    top_k = top_k or settings.RAG_TOP_K
    db = SessionLocal()
    try:
        candidates = _collect_candidates(db, kb_id, query, top_k, mode)
        keywords = extract_keywords(query)
        ranked = rerank(query, candidates, keywords=keywords)
        items = _format_items(db, ranked, top_k, enriched=True)
        scores = [c["score"] for c in ranked[:top_k]]
        stats = {
            "query": query,
            "keywords": keywords,
            "candidate_count": len(candidates),
            "returned": len(items),
            "top_score": round(max(scores), 4) if scores else 0.0,
            "mean_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "lexical_hit_count": sum(1 for c in ranked[:top_k] if c.get("matched_keywords")),
        }
        return {"items": items, "stats": stats}
    finally:
        db.close()
