"""向量化：按知识库绑定的向量模型调用 + hash 兜底。

改造（2026-11-08）：此前模型固定取全局 settings.EMBEDDING_*，知识库上的 embedding_model 只是记录；
现在按知识库绑定的 EmbeddingModel 行取客户端，同一次入库/检索用同一份配置。

拿不到模型行时退回全局 EMBEDDING_*（存量库在迁移里绑到全局那个模型，这里只是防御）：
配置缺了不该让检索整条断掉，但要留日志——静默用错模型比报错更难查。

hash 兜底只保证"检索链路不中断"，语义召回能力远低于真实向量模型，
因此每次降级都要留日志，并通过 embedding_status() 暴露给健康检查与系统状态接口 ——
静默降级会让人以为检索效果差是算法问题，实际上是根本没在用向量模型。
"""
import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.config import settings
from app.core.http import async_client, sync_client

logger = logging.getLogger(__name__)

MODE_MODEL = "model"  # 真实向量模型
MODE_HASH = "hash"    # 本地 hash 兜底
HASH_MODEL_NAME = "hash-fallback"

# 按 api_base + model + key 指纹缓存客户端：入库是多线程并发调用的，每次都构造会把连接池建一堆；
# 但配置改了（页面上编辑模型）必须能立刻生效，所以 key 里带上会变的字段，变了自然就是新客户端。
_clients: dict[tuple, OpenAIEmbeddings] = {}
# 入库流水线会从多个线程同时调：懒初始化加锁，避免并发构造出多个客户端
_clients_lock = threading.Lock()
# 最近一次向量模型调用失败的记录；调用成功后清空，因此非空即代表"当前处于故障降级"
_last_failure: dict | None = None


@dataclass(frozen=True)
class EmbeddingSpec:
    """一次向量化要用的模型配置。

    刻意不直接传 ORM 行：入库在后台线程里跑、检索在请求里跑，两边都不该把 Session 带出去。
    """

    model: str
    api_base: str
    api_key: str
    dim: int
    request_size: int

    @property
    def fingerprint(self) -> tuple:
        """缓存键：含 api_key 的哈希而非明文（字典会出现在 repr / 异常信息里）。"""
        return (self.api_base, self.model, self.dim,
                hashlib.sha256((self.api_key or "").encode()).hexdigest()[:16])


def spec_from_settings() -> EmbeddingSpec:
    """全局 .env 配置 → EmbeddingSpec。库里没有对应模型行时的兜底，也是 system/status 的取值来源。"""
    return EmbeddingSpec(
        model=settings.EMBEDDING_MODEL,
        api_base=settings.EMBEDDING_API_BASE,
        api_key=settings.EMBEDDING_API_KEY,
        dim=settings.EMBEDDING_DIM,
        request_size=settings.EMBEDDING_REQUEST_SIZE,
    )


def spec_from_row(row) -> EmbeddingSpec:
    """embedding_models 行 → EmbeddingSpec。解密失败由调用方处理（库换过 AES_KEY 时会抛 BizError）。"""
    from app.core.security import decrypt_secret

    return EmbeddingSpec(
        model=row.model_name,
        api_base=row.api_base,
        api_key=decrypt_secret(row.api_key_enc),
        dim=row.dim,
        request_size=row.request_size or settings.EMBEDDING_REQUEST_SIZE,
    )


def get_embeddings(spec: EmbeddingSpec | None = None) -> OpenAIEmbeddings:
    """取（并缓存）指定配置的向量客户端。spec 为空时用全局 .env 配置。"""
    spec = spec or spec_from_settings()
    with _clients_lock:
        cached = _clients.get(spec.fingerprint)
        if cached is None:
            cached = OpenAIEmbeddings(
                model=spec.model,
                # 这个参数要 SecretStr 或返回密钥的可调用对象，直接给 str 检查器不认（运行时会自己包一层）；
                # 这里显式包成 SecretStr，等价写法，也避免密钥以明文 str 在调用链上多传一手。
                api_key=SecretStr(spec.api_key or "dummy"),
                base_url=spec.api_base.rstrip("/") if spec.api_base else None,
                dimensions=spec.dim,
                chunk_size=spec.request_size,  # 单次请求条数上限（阿里云百炼 20）；入库时可按页面设置逐次覆盖
                check_embedding_ctx_length=False,  # 直接传原始文本，不做 tokenize（阿里云不支持 token 数组）
                # 本机 oMLX 这类回环地址不走代理环境变量（否则开发机的 HTTP_PROXY 会把请求拦成 502）
                http_client=sync_client(spec.api_base, 60),
                http_async_client=async_client(spec.api_base, 60),
            )
            _clients[spec.fingerprint] = cached
        return cached


def clear_client_cache() -> None:
    """配置改了之后清掉缓存的客户端。模型被编辑（换地址 / 换密钥 / 换模型名）时由服务层调用。"""
    with _clients_lock:
        _clients.clear()


def is_configured(spec: EmbeddingSpec | None = None) -> bool:
    """是否配置了真实向量模型。未配置时全程走 hash，不算故障，属配置性降级。"""
    spec = spec or spec_from_settings()
    return bool(spec.api_key)


def _record_failure(exc: Exception, spec: EmbeddingSpec) -> None:
    global _last_failure
    _last_failure = {"at": datetime.now(timezone.utc).isoformat(), "error": str(exc)[:300], "model": spec.model}


def _clear_failure(spec: EmbeddingSpec) -> None:
    global _last_failure
    if _last_failure is not None:
        logger.info("向量模型已恢复：model=%s", spec.model)
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


@dataclass(frozen=True)
class EmbeddingResult:
    """向量结果 + 实际使用的后端，调用方据此把降级信息写进切片 meta。"""

    vectors: list
    mode: str
    model: str
    dim: int


def _hash_result(texts: list, spec: EmbeddingSpec) -> EmbeddingResult:
    return EmbeddingResult([_hash_embedding(t, spec.dim) for t in texts], MODE_HASH, HASH_MODEL_NAME, spec.dim)


def embed_texts_detailed(texts: list, request_size: int | None = None, spec: EmbeddingSpec | None = None) -> EmbeddingResult:
    """批量向量化，同时返回实际使用的后端（供写入切片 meta）。

    request_size：单次请求携带的条数（超过就串行分多次），不传用 spec.request_size；入库流水线按页面设置传入。
    spec：知识库绑定的向量模型；不传用全局 .env 配置（检索兜底、自检）。
    """
    spec = spec or spec_from_settings()
    if is_configured(spec):
        try:
            # 只在调用方明确指定时才传 chunk_size：不传等价于用客户端自身的默认值
            vectors = get_embeddings(spec).embed_documents(texts, **({"chunk_size": request_size} if request_size else {}))
            _clear_failure(spec)
            return EmbeddingResult(vectors, MODE_MODEL, spec.model, spec.dim)
        except Exception as e:
            # 额度耗尽/超时/网络故障：降级 hash 保证入库不中断，但必须留下 WARN 与降级状态
            _record_failure(e, spec)
            logger.warning(
                "向量模型调用失败，本批 %d 条降级为 hash 向量：model=%s error=%s",
                len(texts), spec.model, e,
            )
    return _hash_result(texts, spec)


def embed_texts(texts: list, spec: EmbeddingSpec | None = None) -> list:
    """批量向量化的便捷封装：只返回向量列表（降级信息需用 embed_texts_detailed 获取）。"""
    return embed_texts_detailed(texts, spec=spec).vectors


def embed_query(text: str, spec: EmbeddingSpec | None = None) -> list:
    spec = spec or spec_from_settings()
    if is_configured(spec):
        try:
            vec = get_embeddings(spec).embed_query(text)
            _clear_failure(spec)
            return vec
        except Exception as e:
            _record_failure(e, spec)
            logger.warning("向量模型调用失败，本次检索降级为 hash 向量：model=%s error=%s", spec.model, e)
    return _hash_embedding(text, spec.dim)


def embedding_status() -> dict:
    """当前向量后端状态（取全局 .env 配置）。mode=hash 表示检索正处于降级状态，前端据此提示。

    这里报的是全局默认配置的状态，用于健康检查与系统状态自检；各知识库实际用的模型见 embedding_models 表。
    """
    spec = spec_from_settings()
    if not is_configured(spec):
        return {
            "mode": MODE_HASH, "model": HASH_MODEL_NAME, "dim": spec.dim, "configured": False,
            "reason": "未配置 EMBEDDING_API_KEY，检索使用本地 hash 向量，语义召回能力有限",
            "last_error": None,
        }
    if _last_failure is not None:
        return {
            "mode": MODE_HASH, "model": HASH_MODEL_NAME, "dim": spec.dim, "configured": True,
            "reason": f"向量模型 {_last_failure.get('model') or spec.model} 调用失败，已降级为 hash 向量",
            "last_error": _last_failure,
        }
    return {
        "mode": MODE_MODEL, "model": spec.model, "dim": spec.dim, "configured": True,
        "reason": None, "last_error": None,
    }
