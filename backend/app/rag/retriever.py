import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, or_, select
from sqlalchemy.orm import defer

from app.config import settings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.rag.embeddings import embed_query
from app.rag.rerank import MODE_MODEL, extract_keywords, rerank, rerank_status

RRF_K = 60  # RRF 倒排融合常数


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
    """逐条鉴权（第二道闸门）：即使检索层漏过，这里按 chunk 权限标签再校验一次。

    与 _acl_condition 保持一致：存量 chunk 无 is_public 标签时视为公开。
    """
    if role == "admin":
        return True
    meta = meta or {}
    if meta.get("is_public") is not False:  # 缺失(None)或 True 均视为公开
        return True
    roles = meta.get("visible_roles") or []
    return bool(role) and role in roles


def _rrf_fuse(candidates: dict) -> None:
    """RRF 倒排融合：向量排名 + 关键词排名 → RRF score（替代简单加权）。"""
    for c in candidates.values():
        rrf = 0.0
        if c.get("vector_rank"):
            rrf += 1.0 / (RRF_K + c["vector_rank"])
        if c.get("keyword_rank"):
            rrf += 1.0 / (RRF_K + c["keyword_rank"])
        c["score"] = round(rrf, 6)


def _collect_candidates(db, kb_id: int, query: str, top_k: int, mode: str, role: str = None, timings: dict | None = None) -> list:
    """召回候选池：向量 + 关键词两路召回，保留各自排名，RRF 倒排融合。

    mode="vector" 时跳过关键词召回，只走向量一路；其余取值（hybrid）两路都走。
    权限过滤前置：先按 ACL 过滤，再做相似度召回，无权 chunk 根本不会被召回。
    """
    timings = timings if timings is not None else {}
    started = time.perf_counter()
    vec = embed_query(query)
    timings["embed_ms"] = int((time.perf_counter() - started) * 1000)
    acl = _acl_condition(role)
    candidates: dict = {}

    def _conds():
        c = [DocumentChunk.kb_id == kb_id]
        if acl is not None:
            c.append(acl)
        return c

    # 1. 向量召回（保留排名）
    dist = DocumentChunk.embedding.cosine_distance(vec)
    # 候选行不加载 embedding 列：每条 1024 维 4KB，一次检索上百条候选全拉回来毫无用处（远程库上占大头）；排序由数据库完成
    stmt = select(DocumentChunk, dist).options(defer(DocumentChunk.embedding)).where(*_conds()).order_by(dist).limit(top_k * 3)
    started = time.perf_counter()
    vector_rows = db.execute(stmt).all()
    timings["vector_ms"] = int((time.perf_counter() - started) * 1000)
    for rank, (chunk, distance) in enumerate(vector_rows, start=1):
        candidates[chunk.id] = {
            "chunk": chunk,
            "content": chunk.content,
            "vector_score": 1 - float(distance),
            "keyword_score": 0.0,
            "vector_rank": rank,
            "keyword_rank": 0,
            "matched": set(),
        }

    # 2. 关键词召回（多关键词并发检索）
    keywords = extract_keywords(query)
    started = time.perf_counter()
    if mode != "vector" and keywords:
        def _search(kw: str):
            db2 = SessionLocal()
            try:
                conds = [DocumentChunk.kb_id == kb_id, DocumentChunk.content.ilike(f"%{kw}%")]
                if acl is not None:
                    conds.append(acl)
                stmt = select(DocumentChunk).options(defer(DocumentChunk.embedding)).where(*conds).limit(top_k * 2)
                return [(chunk.id, chunk, kw) for chunk in db2.execute(stmt).scalars()]
            finally:
                db2.close()

        with ThreadPoolExecutor(max_workers=min(8, len(keywords))) as ex:
            for hits in ex.map(_search, keywords):
                for cid, chunk, kw in hits:
                    if cid not in candidates:
                        candidates[cid] = {
                            "chunk": chunk,
                            "content": chunk.content,
                            "vector_score": 0.0,
                            "keyword_score": 0.0,
                            "vector_rank": 0,
                            "keyword_rank": 0,
                            "matched": set(),
                        }
                    candidates[cid]["matched"].add(kw)
                    candidates[cid]["keyword_score"] = len(candidates[cid]["matched"])

        # 关键词排名：按命中关键词数量降序
        kw_sorted = sorted(candidates.values(), key=lambda c: -c["keyword_score"])
        for rank, c in enumerate(kw_sorted, start=1):
            if c["keyword_score"] > 0:
                c["keyword_rank"] = rank

    timings["keyword_ms"] = int((time.perf_counter() - started) * 1000)
    timings["keyword_count"] = len(keywords)
    _rrf_fuse(candidates)
    return list(candidates.values())


def _prune(ranked: list, min_score: float = 0.01, gap_ratio: float = 0.35) -> list:
    """重排后淘汰无关块：低于绝对阈值，或与 top1 差距过大（相对阈值）的丢弃。

    保证送入 LLM 的只有强相关块，无关内容不会污染大模型判断。
    """
    if not ranked:
        return ranked
    top = ranked[0].get("score", 0.0) or 0.0
    kept = []
    for c in ranked:
        s = c.get("score", 0.0) or 0.0
        if s >= min_score and (top <= 0 or s >= top * gap_ratio):
            kept.append(c)
    return kept


def _format_items(db, ranked: list, top_k: int, enriched: bool = False) -> list:
    """把重排后的候选组装成对外返回结构（content/score/chunk_id/doc_id/doc_name/meta）。

    enriched=True 时附加向量分/关键词分与命中关键词，供评测与调试接口使用。
    """
    items = []
    top = ranked[:top_k]
    # 文档名一次 IN 查询装配，不逐条 db.get（远程库上每次往返几十毫秒）
    doc_ids = {c["chunk"].doc_id for c in top}
    doc_names = {d.id: d.name for d in db.execute(select(Document).where(Document.id.in_(doc_ids))).scalars()} if doc_ids else {}
    for c in top:
        chunk = c["chunk"]
        item = {
            "content": chunk.content,  # 完整文本块，不截断
            "score": c["score"],
            "chunk_id": chunk.id,
            "doc_id": chunk.doc_id,
            "doc_name": doc_names.get(chunk.doc_id, ""),
            "meta": chunk.meta or {},
            "rerank_mode": c.get("rerank_mode"),
            "rerank_score": c.get("rerank_score"),
        }
        if enriched:
            item["vector_score"] = round(c.get("vector_score", 0.0), 4)
            item["keyword_score"] = round(c.get("keyword_score", 0.0), 4)
            item["matched_keywords"] = sorted(c.get("matched", set()))
        items.append(item)
    return items


def _dedupe(ranked: list) -> list:
    """内容完全相同的切片只保留分数最高的一条：表格数据里同一药品会以不同批准文号重复出现，
    原样返回会让引用的 top_k 被三条一模一样的文本占满（2026-09-06 药品说明书导入后发现）。"""
    seen: set = set()
    kept = []
    for c in ranked:
        key = (c.get("content") or "").strip()
        if key in seen:
            continue
        seen.add(key)
        kept.append(c)
    return kept


def _rank_and_authorize(query: str, candidates: list, role: str, keywords: list = None) -> tuple[list, int]:
    """重排 + 淘汰 + 逐条鉴权：返回 (有权重排结果, 鉴权剔除数)。

    模型重排的分数分布与词法完全不同（相关 ≈ 0.99、无关 ≈ 0），淘汰阈值按重排模式分别取配置。
    """
    ranked = rerank(query, candidates, keywords=keywords)
    if ranked and ranked[0].get("rerank_mode") == MODE_MODEL:
        ranked = _prune(ranked, min_score=settings.RERANK_MIN_SCORE, gap_ratio=settings.RERANK_GAP_RATIO)
    else:
        ranked = _prune(ranked)
    ranked = _dedupe(ranked)
    kept, rejected = [], 0
    for c in ranked:
        if _authorize(role, c.get("chunk").meta):
            kept.append(c)
        else:
            rejected += 1
    return kept, rejected


def retrieve(kb_id: int, query: str, top_k: int = None, mode: str = "hybrid", role: str = None) -> list:
    """RRF 融合召回 + 重排淘汰 + 权限过滤，返回完整文本块（content/score/doc_id/doc_name/meta）。"""
    top_k = top_k or settings.RAG_TOP_K
    db = SessionLocal()
    try:
        candidates = _collect_candidates(db, kb_id, query, top_k, mode, role)
        ranked, _ = _rank_and_authorize(query, candidates, role)
        return _format_items(db, ranked, top_k, enriched=False)
    finally:
        db.close()


def retrieve_with_stats(kb_id: int, query: str, top_k: int = None, mode: str = "hybrid", role: str = None) -> dict:
    """检索 + 召回质量统计（含 RRF、淘汰、鉴权剔除数），供评测/调试接口使用。"""
    top_k = top_k or settings.RAG_TOP_K
    db = SessionLocal()
    try:
        timings: dict = {}
        candidates = _collect_candidates(db, kb_id, query, top_k, mode, role, timings=timings)
        keywords = extract_keywords(query)
        started = time.perf_counter()
        ranked, rejected = _rank_and_authorize(query, candidates, role, keywords=keywords)
        timings["rerank_ms"] = int((time.perf_counter() - started) * 1000)
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
            # 本次实际用的重排后端；全部被淘汰时也要能看出走的是模型还是词法，没有候选才是 None
            "rerank_mode": (rerank_status()["mode"] if candidates else None),
            # 各阶段耗时（毫秒）：评测页据此看慢在哪一段
            "timings": timings,
        }
        return {"items": items, "stats": stats}
    finally:
        db.close()
