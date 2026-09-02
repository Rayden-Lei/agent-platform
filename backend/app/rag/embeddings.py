import hashlib

from langchain_openai import OpenAIEmbeddings

from app.config import settings

_embeddings = None


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


def _hash_embedding(text: str, dim: int) -> list:
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


def embed_texts(texts: list) -> list:
    if settings.EMBEDDING_API_KEY:
        try:
            return get_embeddings().embed_documents(texts)
        except Exception:
            # API 失败（额度耗尽/超时/网络）时降级 hash，保证检索不中断
            pass
    return [_hash_embedding(t, settings.EMBEDDING_DIM) for t in texts]


def embed_query(text: str) -> list:
    if settings.EMBEDDING_API_KEY:
        try:
            return get_embeddings().embed_query(text)
        except Exception:
            pass
    return _hash_embedding(text, settings.EMBEDDING_DIM)
