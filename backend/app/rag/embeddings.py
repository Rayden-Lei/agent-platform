"""向量化：真实向量模型 + hash 兜底。

hash 兜底只保证"检索链路不中断"，语义召回能力远低于真实向量模型，
因此每次降级都要留日志，并通过 embedding_status() 暴露给健康检查与系统状态接口 ——
静默降级会让人以为检索效果差是算法问题，实际上是根本没在用向量模型。
"""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from langchain_openai import OpenAIEmbeddings

from app.config import settings

logger = logging.getLogger(__name__)

MODE_MODEL = "model"  # 真实向量模型
MODE_HASH = "hash"    # 本地 hash 兜底
HASH_MODEL_NAME = "hash-fallback"

_embeddings = None
# 最近一次向量模型调用失败的记录；调用成功后清空，因此非空即代表"当前处于故障降级"
_last_failure: dict | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    """向量结果 + 实际使用的后端，调用方据此把降级信息写进切片 meta。"""

    vectors: list
    mode: str
    model: str
    dim: int


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.EMBEDDING_API_KEY or "dummy",
            base_url=settings.EMBEDDING_API_BASE.rstrip("/") if settings.EMBEDDING_API_BASE else None,
            dimensions=settings.EMBEDDING_DIM,
            chunk_size=20,  # 阿里云百炼 embedding 单次上限 20 条
            check_embedding_ctx_length=False,  # 直接传原始文本，不做 tokenize（阿里云不支持 token 数组）
        )
    return _embeddings


def is_configured() -> bool:
    """是否配置了真实向量模型。未配置时全程走 hash，不算故障，属配置性降级。"""
    return bool(settings.EMBEDDING_API_KEY)


def _record_failure(exc: Exception) -> None:
    global _last_failure
    _last_failure = {"at": datetime.now(timezone.utc).isoformat(), "error": str(exc)[:300]}


def _clear_failure() -> None:
    global _last_failure
    if _last_failure is not None:
        logger.info("向量模型已恢复：model=%s", settings.EMBEDDING_MODEL)
    _last_failure = None


def _hash_embedding(text: str, dim: int) -> list:
    """本地 hash 向量：词袋（单词+双字）按 md5 散列到 dim 维并归一化。

    只保证"有向量可用"不保证语义相似性——这是向量模型不可用时的降级路径。
    """
    vec = [0.0] * dim
    for token in text.lower().split():
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    for i in range(len(text) - 1):
        bg = text[i:i + 2]
        h = int(hashlib.md5(bg.encode()).hexdigest(), 16)
        vec[h % dim] += 0.5
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _hash_result(texts: list) -> EmbeddingResult:
    dim = settings.EMBEDDING_DIM
    return EmbeddingResult([_hash_embedding(t, dim) for t in texts], MODE_HASH, HASH_MODEL_NAME, dim)


def embed_texts_detailed(texts: list) -> EmbeddingResult:
    """批量向量化，同时返回实际使用的后端（供写入切片 meta）。"""
    if is_configured():
        try:
            vectors = get_embeddings().embed_documents(texts)
            _clear_failure()
            return EmbeddingResult(vectors, MODE_MODEL, settings.EMBEDDING_MODEL, settings.EMBEDDING_DIM)
        except Exception as e:
            # 额度耗尽/超时/网络故障：降级 hash 保证入库不中断，但必须留下 WARN 与降级状态
            _record_failure(e)
            logger.warning(
                "向量模型调用失败，本批 %d 条降级为 hash 向量：model=%s error=%s",
                len(texts), settings.EMBEDDING_MODEL, e,
            )
    return _hash_result(texts)


def embed_texts(texts: list) -> list:
    """批量向量化的便捷封装：只返回向量列表（降级信息需用 embed_texts_detailed 获取）。"""
    return embed_texts_detailed(texts).vectors


def embed_query(text: str) -> list:
    if is_configured():
        try:
            vec = get_embeddings().embed_query(text)
            _clear_failure()
            return vec
        except Exception as e:
            _record_failure(e)
            logger.warning("向量模型调用失败，本次检索降级为 hash 向量：model=%s error=%s", settings.EMBEDDING_MODEL, e)
    return _hash_embedding(text, settings.EMBEDDING_DIM)


def embedding_status() -> dict:
    """当前向量后端状态。mode=hash 表示检索正处于降级状态，前端据此提示使用者。"""
    dim = settings.EMBEDDING_DIM
    if not is_configured():
        return {
            "mode": MODE_HASH, "model": HASH_MODEL_NAME, "dim": dim, "configured": False,
            "reason": "未配置 EMBEDDING_API_KEY，检索使用本地 hash 向量，语义召回能力有限",
            "last_error": None,
        }
    if _last_failure is not None:
        return {
            "mode": MODE_HASH, "model": HASH_MODEL_NAME, "dim": dim, "configured": True,
            "reason": f"向量模型 {settings.EMBEDDING_MODEL} 调用失败，已降级为 hash 向量",
            "last_error": _last_failure,
        }
    return {
        "mode": MODE_MODEL, "model": settings.EMBEDDING_MODEL, "dim": dim, "configured": True,
        "reason": None, "last_error": None,
    }
