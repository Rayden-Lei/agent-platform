import logging
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.core.exceptions import BizError
from app.db.models import Document, DocumentChunk, EmbeddingModel, KnowledgeBase
from app.db.session import SessionLocal
from app.rag import embedding_dims
from app.rag.embeddings import embed_query
from app.rag.rerank import MODE_MODEL, extract_keywords, rerank, rerank_status
from app.services.settings_service import runtime_value

logger = logging.getLogger(__name__)

RRF_K = 60  # RRF 倒排融合常数


def kb_allows(role: str | None, kb: KnowledgeBase | None, kb_scope: list | None = None) -> bool:
    """知识库级鉴权（第一道闸门，召回之前）：admin 可见全部；其他角色只能检索公开库，或 visible_roles 含该角色的库。

    读的是 knowledge_bases 行的当前值。切片 meta 里的 is_public / visible_roles 是入库时的快照，改权限后不回写，
    拿它鉴权会让改权限对存量切片不生效（2026-09-25 之前就是这样），现在只留作审计。库不存在视为无权。
    管理面的 kb_service.visible_kb_filter 是同一规则的 SQL 写法；知识库详情的"各身份能否检索"直接调本函数（docs/15 KB-01）。

    kb_scope 不为 None 表示 API Key 发起的检索（docs/15 3.7.1，D-07 / D-09）：只放行公开库，以及在 Key 的 kb_ids 内、
    且归属人当前角色可见的库。不因归属人是 admin 就放行受限库——否则 admin 给智能体建一个 Key，智能体绑定的
    "仅管理员可见"库就对 Key 背后的所有终端用户开放了。

    role 为 None 表示匿名访客（分享出去的访客会话就是这样调的）：既不是 admin 也没有角色，
    只能命中公开库；kb 为 None 表示库不存在，按无权处理。
    """
    if kb is None:
        return False
    if kb_scope is not None:
        return bool(kb.is_public) or (kb.id in kb_scope and kb_allows(role, kb))
    if role == "admin":
        return True
    return bool(kb.is_public) or (bool(role) and role in (kb.visible_roles or []))


class KBUnsearchable(Exception):
    """知识库当前无法检索：绑定的向量模型缺失 / 停用 / 维度不受支持。

    为什么是异常而不是"退回全局配置"（2026-11-15 改）：切片向量是**库绑定的那个模型**产的，
    查询向量必须来自同一个模型，余弦距离才有意义。以前退回全局 .env 配置在"全局维度恰好等于
    库维度"时是碰巧对的，支持多维度之后这种巧合不再成立 —— 1024 维的库拿 768 维的查询向量去比，
    pgvector 直接报维度不匹配；更糟的是维度相同但模型不同时，会安静地返回一堆垃圾结果。
    检索是对话主链路，所以这里仍不抛到用户面前：由调用方捕获后把该库当"无结果"处理并记日志，
    与其他库的结果互不影响（chat_service._retrieve_all 是按 (库, 查询) 并发调用的）。
    """


def unsearchable_reason(kb_name: str, embedding_model_id: int | None, model: EmbeddingModel | None) -> str | None:
    """知识库当前无法检索的原因；可检索时返回 None。

    三个前置条件缺一不可：模型行还在、模型是启用的、维度在支持集合里。
    维度不在支持集合里意味着切片表没有对应的列，任何查询都无从下手。

    为什么是纯函数、参数用标量而不是 KnowledgeBase 行：系统状态页要一次列出**所有**不可检索的库，
    那是"一次查询取回 knowledge_bases + embedding_models，再逐行判断"，不能逐库 db.get（06 第 1 节禁循环内 IO）。
    检索路径（_kb_vector）与状态页共用本函数，判断规则只有这一处，不会出现
    "检索认为不可用、状态页认为正常"这种对不上的情况。
    """
    if model is None:
        return f"知识库「{kb_name}」绑定的向量模型不存在（id={embedding_model_id}），请重新配置"
    if not model.is_enabled:
        return f"知识库「{kb_name}」绑定的向量模型「{model.name}」已停用"
    if not embedding_dims.is_supported(model.dim):
        return f"知识库「{kb_name}」的向量模型维度 {model.dim} 不受支持（可选 {list(embedding_dims.SUPPORTED_DIMS)}）"
    return None


def _kb_vector(db, kb: KnowledgeBase) -> tuple:
    """知识库当前该用的 (向量模型配置, 维度列)；不满足检索条件时抛 KBUnsearchable。

    三个前置条件见 unsearchable_reason（判断规则与系统状态页共用那一处）。
    模型行只取一次（先判断、再由同一行建 spec）：检索是对话主链路，不能为了一次判断多打一次远程库。
    """
    from app.rag.embeddings import spec_from_row

    model = db.get(EmbeddingModel, kb.embedding_model_id) if kb.embedding_model_id else None
    reason = unsearchable_reason(kb.name, kb.embedding_model_id, model)
    if reason:
        raise KBUnsearchable(f"知识库 {kb.id} 不可检索：{reason}")
    try:
        # 解密失败（库换过 AES_KEY）也按"不可检索"处理：检索主链路上抛 BizError 会让对话 500、
        # 工作流节点 failed，而这个库本来就只是"这一路召回不可用"。
        spec = spec_from_row(model)
    except BizError as e:
        raise KBUnsearchable(f"知识库 {kb.id} 不可检索：{e}") from e
    return spec, embedding_dims.orm_column(spec.dim)


def _authorize(role: str | None, kb: KnowledgeBase, chunk, kb_scope: list | None = None) -> bool:
    """逐条鉴权（第二道闸门，重排之后）：切片必须属于本次鉴权通过的那个库，且该库对角色（与 Key 的范围）可见。

    与 kb_allows 同一口径（06 第 8 节：两道闸门语义一致）；召回层万一混进别的库的切片，在这里拦下。
    """
    return chunk.kb_id == kb.id and kb_allows(role, kb, kb_scope)


def _rrf_fuse(candidates: dict) -> None:
    """RRF 倒排融合：向量排名 + 关键词排名 → RRF score（替代简单加权）。"""
    for c in candidates.values():
        rrf = 0.0
        if c.get("vector_rank"):
            rrf += 1.0 / (RRF_K + c["vector_rank"])
        if c.get("keyword_rank"):
            rrf += 1.0 / (RRF_K + c["keyword_rank"])
        c["score"] = round(rrf, 6)


def _collect_candidates(db, kb_id: int, query: str, top_k: int, mode: str, spec, column,
                        timings: dict | None = None) -> list:
    """召回候选池：向量 + 关键词两路召回，保留各自排名，RRF 倒排融合。

    spec 是知识库绑定的向量模型配置，column 是它维度对应的切片列（embedding_dims.orm_column）：
    查询向量必须与切片向量同一个模型、同一个维度列产出，否则余弦距离没有意义
    （不同模型的向量空间不可比；不同维度的列在 pgvector 里根本算不了距离）。

    mode="vector" 时跳过关键词召回，只走向量一路；其余取值（hybrid）两路都走。
    调用前必须已过 kb_allows：无权的库根本不进这里，连查询向量化都不做。
    """
    timings = timings if timings is not None else {}
    started = time.perf_counter()
    vec = embed_query(query, spec)
    timings["embed_ms"] = int((time.perf_counter() - started) * 1000)
    candidates: dict = {}

    # 1. 向量召回（保留排名）
    # 只在库自己维度那一列上算距离，并要求该列非空：一行只有一列有值，别的维度列是 NULL，
    # 不过滤会把这些"没有本维度向量"的行按 NULL 距离排进来，变成一堆与查询无关的垃圾结果。
    dist = column.cosine_distance(vec)
    stmt = (select(DocumentChunk, dist)
            .options(*embedding_dims.defer_options())
            .where(DocumentChunk.kb_id == kb_id, column.is_not(None))
            .order_by(dist).limit(top_k * 3))
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
                # 关键词召回也要按维度列过滤：一行只有"入库时那个维度"的列有值，
                # 本库维度列是 NULL 的切片说明它不是用本库当前的模型向量化的（存量迁移遗留 /
                # 换过模型还没重建），不属于本库的检索空间。只过滤向量一路的话，
                # 这类切片会从关键词一路混进结果，用户看到的是"向量分 0 却排在结果里"的垃圾命中。
                conds = [DocumentChunk.kb_id == kb_id, column.is_not(None),
                         DocumentChunk.content.ilike(f"%{kw}%")]
                # 候选只用来拼关键词命中，向量列一条都不加载（一条 1536 维 6KB，上百条候选在远程库上是纯浪费）
                stmt = select(DocumentChunk).options(*embedding_dims.defer_options()).where(*conds).limit(top_k * 2)
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


def _rank_and_authorize(query: str, candidates: list, role: str | None, kb: KnowledgeBase | None, keywords: list | None = None, kb_scope: list | None = None) -> tuple[list, int]:
    """重排 + 淘汰 + 逐条鉴权：返回 (有权重排结果, 鉴权剔除数)。

    模型重排的分数分布与词法完全不同（相关 ≈ 0.99、无关 ≈ 0），淘汰阈值按重排模式分别取配置。
    """
    ranked = rerank(query, candidates, keywords=keywords)
    if ranked and ranked[0].get("rerank_mode") == MODE_MODEL:
        ranked = _prune(ranked, min_score=runtime_value("rerank_min_score"), gap_ratio=runtime_value("rerank_gap_ratio"))
    else:
        ranked = _prune(ranked)
    ranked = _dedupe(ranked)
    # kb 为 None 时一条都不放行：库不存在，切片也就谈不上属于它。
    if kb is None:
        return [], len(ranked)
    kept, rejected = [], 0
    for c in ranked:
        if _authorize(role, kb, c.get("chunk"), kb_scope):
            kept.append(c)
        else:
            rejected += 1
    return kept, rejected


def retrieve(kb_id: int, query: str, top_k: int | None = None, mode: str = "hybrid", role: str | None = None, kb_scope: list | None = None) -> list:
    """RRF 融合召回 + 重排淘汰 + 权限过滤，返回完整文本块（content/score/doc_id/doc_name/meta）。kb_scope 见 kb_allows。"""
    top_k = top_k or runtime_value("rag_top_k")
    db = SessionLocal()
    try:
        kb = db.get(KnowledgeBase, kb_id)
        if not kb_allows(role, kb, kb_scope):
            return []
        try:
            spec, column = _kb_vector(db, kb)
        except KBUnsearchable as e:
            # 该库不参与本次检索：返回空而不是拿错向量空间的模型硬查（见 KBUnsearchable）
            logger.warning("跳过检索：%s", e)
            return []
        candidates = _collect_candidates(db, kb_id, query, top_k, mode, spec, column)
        ranked, _ = _rank_and_authorize(query, candidates, role, kb, kb_scope=kb_scope)
        return _format_items(db, ranked, top_k, enriched=False)
    finally:
        db.close()


def retrieve_with_stats(kb_id: int, query: str, top_k: int | None = None, mode: str = "hybrid", role: str | None = None, kb_scope: list | None = None) -> dict:
    """检索 + 召回质量统计（含 RRF、淘汰、鉴权剔除数），供评测 / 调试 / 对话使用。kb_scope 见 kb_allows（API Key 对话才传）。"""
    top_k = top_k or runtime_value("rag_top_k")
    db = SessionLocal()
    try:
        kb = db.get(KnowledgeBase, kb_id)
        if not kb_allows(role, kb, kb_scope):
            # 无权检索这个库：不召回、不做查询向量化；kb_denied 让评测页与调用方能区分"没命中"和"没权限"
            return {"items": [], "stats": {
                "query": query, "keywords": [], "candidate_count": 0, "acl_rejected": 0, "returned": 0,
                "top_score": 0.0, "mean_score": 0.0, "lexical_hit_count": 0, "rerank_mode": None, "timings": {}, "kb_denied": True,
            }}
        try:
            spec, column = _kb_vector(db, kb)
        except KBUnsearchable as e:
            # 与 retrieve 同口径，但要额外告诉调用方原因：评测页要能区分"没命中"与"库配置坏了"
            logger.warning("跳过检索：%s", e)
            return {"items": [], "stats": {
                "query": query, "keywords": [], "candidate_count": 0, "acl_rejected": 0, "returned": 0,
                "top_score": 0.0, "mean_score": 0.0, "lexical_hit_count": 0, "rerank_mode": None, "timings": {},
                "kb_denied": False, "kb_unsearchable": str(e),
            }}
        timings: dict = {}
        candidates = _collect_candidates(db, kb_id, query, top_k, mode, spec, column, timings=timings)
        keywords = extract_keywords(query)
        started = time.perf_counter()
        ranked, rejected = _rank_and_authorize(query, candidates, role, kb, keywords=keywords, kb_scope=kb_scope)
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
            "kb_denied": False,
            "kb_unsearchable": None,
        }
        return {"items": items, "stats": stats}
    finally:
        db.close()
