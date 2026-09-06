"""检索重排：模型重排（FR-032）+ 词法启发式兜底。

`rerank(query, candidates, keywords)` 接口固定（`06-后端规范.md` 第 8 节），返回按 score 降序的新列表，
每条带 `rerank_mode`（model / lexical）与 `rerank_score`（模型分，词法时为 None）。
配置了 `RERANK_PROVIDER` 时先取前 `RERANK_CANDIDATES` 条送模型，调用失败或超时退回词法重排并打 WARN；
`rerank_status()` 汇报当前模式，接进 `/system/status`：未配置属配置性（不进 degraded），配置了但失败属故障性（进 degraded），
与向量后端的两类降级口径一致。
"""
import logging
import re
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.core.http import trust_env_for

logger = logging.getLogger(__name__)

MODE_MODEL = "model"
MODE_LEXICAL = "lexical"
PROVIDERS = ("cohere", "dashscope")

# 最近一次模型重排失败的记录；调用成功后清空，非空即代表"当前处于故障降级"
_last_failure: dict | None = None


MAX_KEYWORDS = 12


def extract_keywords(query: str) -> list:
    """从查询中提取关键词：英文/数字词 + 中文片段（≤ 4 字整段，更长的切三元组），最多 MAX_KEYWORDS 个，保持出现顺序。

    用三元组而不是二元组：关键词召回的 ILIKE 靠 pg_trgm 索引，模式不足 3 字走不了索引会全表扫描；
    三元组也更像一个词（"适应症"），二元组（"应症"）噪声多。
    """
    keywords: dict = {}
    for w in re.findall(r"[a-zA-Z0-9]+", query):
        if len(w) >= 2:
            keywords.setdefault(w.lower(), None)
    for seg in re.findall(r"[一-龥]+", query):
        if len(seg) <= 4:
            keywords.setdefault(seg, None)
        else:
            for i in range(len(seg) - 2):
                keywords.setdefault(seg[i:i + 3], None)
    return list(keywords)[:MAX_KEYWORDS]


def is_configured() -> bool:
    """是否配置了重排模型。未配置时全程词法，不算故障。"""
    return settings.RERANK_PROVIDER in PROVIDERS and bool(settings.RERANK_API_BASE) and bool(settings.RERANK_MODEL)


def _record_failure(exc: Exception) -> None:
    global _last_failure
    _last_failure = {"at": datetime.now(timezone.utc).isoformat(), "error": str(exc)[:300]}


def _clear_failure() -> None:
    global _last_failure
    if _last_failure is not None:
        logger.info("重排模型已恢复：provider=%s model=%s", settings.RERANK_PROVIDER, settings.RERANK_MODEL)
    _last_failure = None


def rerank_lexical(query: str, candidates: list, keywords: list = None) -> list:
    """词法启发式：query 词元在 content 中的覆盖率（词法命中）与既有混合分各占 50% 融合。"""
    if not candidates:
        return []
    keywords = keywords or extract_keywords(query)
    ranked = []
    for c in candidates:
        content = (c.get("content") or "").lower()
        hits = [kw for kw in keywords if kw.lower() in content]
        coverage = len(hits) / len(keywords) if keywords else 0.0
        length_bonus = min(sum(len(kw) for kw in hits) / 100.0, 1.0)
        lexical = coverage * 0.8 + length_bonus * 0.2
        base = float(c.get("score", 0.0))
        item = dict(c)
        item["lexical_score"] = round(lexical, 4)
        item["matched_keywords"] = hits
        item["score"] = round(base * 0.5 + lexical * 0.5, 4)
        item["rerank_mode"] = MODE_LEXICAL
        item["rerank_score"] = None
        ranked.append(item)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def _request_scores(query: str, documents: list) -> list:
    """调用重排服务，返回与 documents 等长的分数列表。两种请求体：

    cohere：Cohere / Jina / TEI / vLLM / SiliconFlow / oMLX 共用的 `POST /rerank`：
      `{model, query, documents, top_n}` → `results[{index, relevance_score}]`
    dashscope：阿里云百炼 `text-rerank`：`{model, input: {query, documents}, parameters: {top_n, return_documents}}`
      → `output.results[{index, relevance_score}]`
    """
    base = settings.RERANK_API_BASE.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if settings.RERANK_API_KEY:
        headers["Authorization"] = "Bearer " + settings.RERANK_API_KEY
    if settings.RERANK_PROVIDER == "dashscope":
        url = base + "/services/rerank/text-rerank/text-rerank"
        body = {"model": settings.RERANK_MODEL, "input": {"query": query, "documents": documents}, "parameters": {"top_n": len(documents), "return_documents": False}}
    else:
        url = base + "/rerank"
        body = {"model": settings.RERANK_MODEL, "query": query, "documents": documents, "top_n": len(documents)}
    with httpx.Client(timeout=settings.RERANK_TIMEOUT, trust_env=trust_env_for(base)) as client:
        resp = client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    results = payload.get("output", {}).get("results") if settings.RERANK_PROVIDER == "dashscope" else payload.get("results")
    if not isinstance(results, list):
        raise ValueError("重排服务响应缺少 results")
    scores = [0.0] * len(documents)
    for r in results:
        idx = r.get("index")
        if isinstance(idx, int) and 0 <= idx < len(documents):
            scores[idx] = float(r.get("relevance_score", 0.0))
    return scores


def rerank_by_model(query: str, candidates: list) -> list:
    """模型重排：取前 RERANK_CANDIDATES 条候选请求重排服务，score 直接取 relevance_score，按降序返回。失败抛异常由 rerank() 兜底。"""
    top = candidates[: settings.RERANK_CANDIDATES]
    scores = _request_scores(query, [(c.get("content") or "")[:4000] for c in top])
    ranked = []
    for c, s in zip(top, scores):
        item = dict(c)
        item["rerank_mode"] = MODE_MODEL
        item["rerank_score"] = round(s, 6)
        item["score"] = round(s, 6)
        item.setdefault("matched_keywords", [])
        ranked.append(item)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def rerank(query: str, candidates: list, keywords: list = None) -> list:
    """对候选重排，返回按 score 降序的新列表。配置了重排模型走模型，失败退回词法并记录降级；候选为空不调服务。"""
    if not candidates:
        return []
    if is_configured():
        try:
            ranked = rerank_by_model(query, candidates)
            _clear_failure()
            return ranked
        except Exception as e:
            _record_failure(e)
            logger.warning("重排模型调用失败，本次退回词法重排：provider=%s model=%s error=%s", settings.RERANK_PROVIDER, settings.RERANK_MODEL, e)
    return rerank_lexical(query, candidates, keywords)


def rerank_status() -> dict:
    """当前重排后端状态。mode=lexical 且 configured=true 表示正处于故障降级。"""
    if not is_configured():
        return {"mode": MODE_LEXICAL, "configured": False, "provider": settings.RERANK_PROVIDER or None, "model": None, "reason": "未配置 RERANK_PROVIDER，检索使用词法重排", "last_error": None}
    if _last_failure is not None:
        return {"mode": MODE_LEXICAL, "configured": True, "provider": settings.RERANK_PROVIDER, "model": settings.RERANK_MODEL,
                "reason": f"重排模型 {settings.RERANK_MODEL} 调用失败，已退回词法重排", "last_error": _last_failure}
    return {"mode": MODE_MODEL, "configured": True, "provider": settings.RERANK_PROVIDER, "model": settings.RERANK_MODEL, "reason": None, "last_error": None}
