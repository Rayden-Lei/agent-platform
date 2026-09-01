from sqlalchemy import func, or_, select

from app.config import settings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.rag.embeddings import embed_query
from app.rag.rerank import extract_keywords, rerank


def _acl_condition(role: str):
    """构造 chunk 权限过滤条件（先过滤后召回的第一道硬闸门）。

    - admin：不过滤，可见全部
    - 其他角色/匿名：仅 is_public=true，或 visible_roles 包含该角色
    返回 SQLAlchemy 条件；None 表示无过滤。
    """
    if role == "admin":
        return None
    return or_(
        # 存量 chunk 无 is_public 标签时视为公开（兼容旧数据）；新数据由 pipeline 显式打标签
        func.coalesce(DocumentChunk.meta["is_public"].as_boolean(), True) == True,  # noqa: E712
        DocumentChunk.meta["visible_roles"].contains([role]) if role else False,
    )


def _authorize(role: str, meta: dict) -> bool:
    """逐条鉴权（第二道闸门）：即使检索层漏过，这里按 chunk 权限标签再校验一次。"""
    if role == "admin":
        return True
    meta = meta or {}
    if meta.get("is_public"):
        return True
    roles = meta.get("visible_roles") or []
    return bool(role) and role in roles


def _collect_candidates(db, kb_id: int, query: str, top_k: int, mode: str, role: str = None) -> list:
    """召回候选池：向量相似度 + 关键词匹配，计算混合分（向量 0.7 + 关键词 0.3）。

    权限过滤前置：先按 ACL 过滤，再做相似度召回，无权 chunk 根本不会被召回。
    """
    vec = embed_query(query)
    candidates: dict = {}
    acl = _acl_condition(role)

    def _kb_filter():
        return (DocumentChunk.kb_id == kb_id,) if acl is None else (DocumentChunk.kb_id == kb_id, acl)

    # 1. 向量召回（权限过滤 + 相似度排序）
    dist = DocumentChunk.embedding.cosine_distance(vec)
    stmt = select(DocumentChunk, dist).where(*_kb_filter()).order_by(dist).limit(top_k * 3)
    for chunk, distance in db.execute(stmt).all():
        vscore = 1 - float(distance)
        candidates[chunk.id] = {
            "chunk": chunk,
            "content": chunk.content,
            "vector_score": vscore,
            "keyword_score": 0.0,
        }

    # 2. 关键词召回（同样带权限过滤）
    if mode != "vector":
        for kw in extract_keywords(query):
            conds = [DocumentChunk.kb_id == kb_id, DocumentChunk.content.ilike(f"%{kw}%")]
            if acl is not None:
                conds.append(acl)
            kw_stmt = select(DocumentChunk).where(*conds).limit(top_k * 2)
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
            "chunk_id": chunk.id,
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


def _rank_and_authorize(query: str, candidates: list, role: str, keywords: list = None) -> tuple[list, int]:
    """重排 + 逐条鉴权：返回 (有权重排结果, 鉴权剔除数)。"""
    ranked = rerank(query, candidates, keywords=keywords)
    kept, rejected = [], 0
    for c in ranked:
        if _authorize(role, c.get("chunk").meta):
            kept.append(c)
        else:
            rejected += 1
    return kept, rejected


def retrieve(kb_id: int, query: str, top_k: int = None, mode: str = "hybrid", role: str = None) -> list:
    """混合召回 + 重排 + 权限过滤，返回（content/score/doc_id/doc_name/meta）。"""
    top_k = top_k or settings.RAG_TOP_K
    db = SessionLocal()
    try:
        candidates = _collect_candidates(db, kb_id, query, top_k, mode, role)
        ranked, _ = _rank_and_authorize(query, candidates, role)
        return _format_items(db, ranked, top_k, enriched=False)
    finally:
        db.close()


def retrieve_with_stats(kb_id: int, query: str, top_k: int = None, mode: str = "hybrid", role: str = None) -> dict:
    """检索 + 召回质量统计（含权限过滤与鉴权剔除数），供评测/调试接口使用。"""
    top_k = top_k or settings.RAG_TOP_K
    db = SessionLocal()
    try:
        candidates = _collect_candidates(db, kb_id, query, top_k, mode, role)
        keywords = extract_keywords(query)
        ranked, rejected = _rank_and_authorize(query, candidates, role, keywords=keywords)
        items = _format_items(db, ranked, top_k, enriched=True)
        scores = [c["score"] for c in ranked[:top_k]]
        stats = {
            "query": query,
            "keywords": keywords,
            "candidate_count": len(candidates),
            "acl_rejected": rejected,
            "returned": len(items),
            "top_score": round(max(scores), 4) if scores else 0.0,
            "mean_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "lexical_hit_count": sum(1 for c in ranked[:top_k] if c.get("matched_keywords")),
        }
        return {"items": items, "stats": stats}
    finally:
        db.close()
