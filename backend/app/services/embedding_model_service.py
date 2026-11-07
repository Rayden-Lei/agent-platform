"""向量模型服务：embedding_models 表的 CRUD、连通测试与维度校验。

为什么单独一层而不是塞进 model_service：对话模型与向量模型是两套调用协议
（chat/completions vs embeddings），字段、校验、探活方式都不同；混在一起会让人在
"模型"页面选一个只能对话的模型去建知识库，然后入库时报 400。

**维度校验是这里最要紧的一条**：document_chunks.embedding 是定长的 pgvector 列，
向量维度与列宽不一致时 PostgreSQL 直接报错（入库在后台线程里，用户只看到文档 failed）。
所以保存模型时就比对 settings.EMBEDDING_DIM，不一致立即 422 —— 让错误停在表单上。

密钥与 models.api_key_enc 同一口径：AES 加密落库，任何接口只回 has_key。
"""
from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.config import settings
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.http import sync_client
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import EmbeddingModel, KnowledgeBase, User
from app.db.session import rows_to_dict
from app.rag import embeddings

logger = logging.getLogger(__name__)

SORTABLE = {"id": EmbeddingModel.id, "name": EmbeddingModel.name, "provider": EmbeddingModel.provider,
            "updated_at": EmbeddingModel.updated_at}
DIM_MIN, DIM_MAX = 1, 4096
REQUEST_SIZE_MIN, REQUEST_SIZE_MAX = 1, 500


def _to_dict(m: EmbeddingModel, kbs_count: int = 0, creator: str | None = None) -> dict:
    """对外形态：密钥只回 has_key，密文与明文都不出现（与 models / tools 同一口径）。"""
    return {
        "id": m.id, "name": m.name, "provider": m.provider, "api_base": m.api_base,
        "model_name": m.model_name, "dim": m.dim, "request_size": m.request_size,
        "is_enabled": m.is_enabled, "has_key": bool(m.api_key_enc),
        "kbs_count": kbs_count,
        "created_by": m.created_by, "created_by_username": creator,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _creators(db: Session, rows: list) -> dict:
    ids = {m.created_by for m in rows if m.created_by}
    return rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(ids)).all()) if ids else {}


def _kbs_count(db: Session, ids: set[int]) -> dict[int, int]:
    """各模型被多少个知识库绑定。一次 group by 拿完，不逐行查库。"""
    if not ids:
        return {}
    rows = db.query(KnowledgeBase.embedding_model_id, func.count(KnowledgeBase.id)).filter(
        KnowledgeBase.embedding_model_id.in_(ids)
    ).group_by(KnowledgeBase.embedding_model_id).all()
    return {row[0]: int(row[1]) for row in rows}


def _check_dim(dim: int) -> None:
    """维度必须与 document_chunks.embedding 的列宽一致：定长列装不下别的维度，只能在这里拦住。"""
    if not DIM_MIN <= dim <= DIM_MAX:
        raise BizError(422, f"维度必须在 {DIM_MIN}～{DIM_MAX} 之间")
    if dim != settings.EMBEDDING_DIM:
        raise BizError(
            422,
            f"向量维度 {dim} 与切片表列宽 {settings.EMBEDDING_DIM} 不一致："
            f"pgvector 是定长列，装不下别的维度。请用产出 {settings.EMBEDDING_DIM} 维的模型；"
            "要用其他维度需要先做迁移（改列宽并重建全部切片）",
        )


def _check_request_size(size: int) -> None:
    if not REQUEST_SIZE_MIN <= size <= REQUEST_SIZE_MAX:
        raise BizError(422, f"单次请求条数必须在 {REQUEST_SIZE_MIN}～{REQUEST_SIZE_MAX} 之间")


def list_models(db: Session, params: PageParams, q: str | None = None,
                provider: str | None = None, is_enabled: bool | None = None,
                sort: SortParams | None = None) -> dict:
    """向量模型列表（分页），附被多少知识库绑定与创建人。密钥只回 has_key。"""
    query = db.query(EmbeddingModel)
    if q:
        query = query.filter(EmbeddingModel.name.ilike(f"%{q}%"))
    if provider:
        query = query.filter(EmbeddingModel.provider == provider)
    if is_enabled is not None:
        query = query.filter(EmbeddingModel.is_enabled.is_(is_enabled))
    query = apply_sort(query, sort, SORTABLE, [EmbeddingModel.id.desc()])
    page = paginate(query, params)
    rows = page["items"]
    counts = _kbs_count(db, {m.id for m in rows})
    creators = _creators(db, rows)
    page["items"] = [_to_dict(m, counts.get(m.id, 0), creators.get(m.created_by)) for m in rows]
    return page


def get_model(db: Session, model_id: int) -> dict:
    """按 ID 查（含绑定它的知识库清单）。"""
    m = db.get(EmbeddingModel, model_id)
    if m is None:
        raise BizError(404, "向量模型不存在")
    kbs = db.query(KnowledgeBase.id, KnowledgeBase.name).filter(
        KnowledgeBase.embedding_model_id == model_id).order_by(KnowledgeBase.id).all()
    data = _to_dict(m, len(kbs), _creators(db, [m]).get(m.created_by))
    data["knowledge_bases"] = [{"id": row[0], "name": row[1]} for row in kbs]
    return data


def create_model(db: Session, data, user: User) -> dict:
    """新建向量模型。维度必须与列宽一致；密钥必填（新建时没有可沿用的）。"""
    if not data.api_key or not data.api_key.strip():
        raise BizError(422, "请填写 API Key")
    _check_dim(data.dim)
    _check_request_size(data.request_size)
    if db.query(EmbeddingModel).filter(EmbeddingModel.name == data.name).first():
        raise BizError(400, f"向量模型名称「{data.name}」已存在")
    m = EmbeddingModel(
        name=data.name, provider=data.provider, api_base=data.api_base,
        api_key_enc=encrypt_secret(data.api_key), model_name=data.model_name,
        dim=data.dim, request_size=data.request_size, is_enabled=data.is_enabled,
        created_by=user.id,
    )
    db.add(m)
    db.flush()
    record_audit(db, user, "create", "embedding_model", m.id, detail={"name": m.name, "model_name": m.model_name})
    db.refresh(m)
    return _to_dict(m, 0, user.username)


def update_model(db: Session, model_id: int, data, user: User) -> dict:
    """覆盖式更新；api_key 为空表示沿用已有密钥。

    改了地址 / 模型名 / 密钥后必须清掉客户端缓存，否则进程内还拿着旧连接与旧配置，
    表现为"页面上改了却不生效，重启才好"。
    """
    m = db.get(EmbeddingModel, model_id)
    if m is None:
        raise BizError(404, "向量模型不存在")
    _check_dim(data.dim)
    _check_request_size(data.request_size)
    dup = db.query(EmbeddingModel).filter(EmbeddingModel.name == data.name, EmbeddingModel.id != model_id).first()
    if dup:
        raise BizError(400, f"向量模型名称「{data.name}」已存在")

    changed = (m.name != data.name or m.provider != data.provider or m.api_base != data.api_base
               or m.model_name != data.model_name or m.dim != data.dim
               or m.request_size != data.request_size or m.is_enabled != data.is_enabled)
    m.name, m.provider, m.api_base = data.name, data.provider, data.api_base
    m.model_name, m.dim, m.request_size, m.is_enabled = data.model_name, data.dim, data.request_size, data.is_enabled
    if data.api_key:
        m.api_key_enc = encrypt_secret(data.api_key)
    if changed or data.api_key:
        record_audit(db, user, "update", "embedding_model", m.id,
                     detail={"name": m.name, "changed": changed, **({"api_key": "已更换"} if data.api_key else {})})
    db.commit()
    # 配置变了才清缓存：清空不影响正在飞行的请求（它们持有自己的客户端实例）
    if changed or data.api_key:
        embeddings.clear_client_cache()
    db.refresh(m)
    return _to_dict(m, _kbs_count(db, {m.id}).get(m.id, 0), _creators(db, [m]).get(m.created_by))


def toggle_model(db: Session, model_id: int, user: User) -> dict:
    """启用 / 停用。停用被知识库绑定的模型会让那些库无法入库与检索，所以拒绝（要先解绑，而库的模型不可改）。"""
    m = db.get(EmbeddingModel, model_id)
    if m is None:
        raise BizError(404, "向量模型不存在")
    if m.is_enabled and db.query(KnowledgeBase).filter(KnowledgeBase.embedding_model_id == model_id).first():
        raise BizError(400, "仍有知识库绑定这个向量模型，停用后那些库将无法入库与检索")
    m.is_enabled = not m.is_enabled
    record_audit(db, user, "update", "embedding_model", m.id, detail={"is_enabled": m.is_enabled})
    db.commit()
    db.refresh(m)
    return _to_dict(m, _kbs_count(db, {m.id}).get(m.id, 0))


def delete_model(db: Session, model_id: int, user: User) -> None:
    """删除：被知识库绑定时 409（外键 RESTRICT 也会拦，这里提前给可读原因）。"""
    m = db.get(EmbeddingModel, model_id)
    if m is None:
        raise BizError(404, "向量模型不存在")
    bound = db.query(KnowledgeBase).filter(KnowledgeBase.embedding_model_id == model_id).first()
    if bound:
        raise BizError(409, f"仍有知识库「{bound.name}」绑定这个向量模型，不能删除")
    db.delete(m)
    record_audit(db, user, "delete", "embedding_model", model_id, detail={"name": m.name})
    db.commit()
    embeddings.clear_client_cache()


def test_model(db: Session, model_id: int) -> dict:
    """连通测试：真的发一次 embeddings 请求并核对返回维度。

    失败不抛异常而是 ok=false 带原因 —— 测试按钮的用途就是看错误信息，
    抛成 5xx 会让前端只能弹一句"服务器错误"。
    """
    m = db.get(EmbeddingModel, model_id)
    if m is None:
        raise BizError(404, "向量模型不存在")
    try:
        client = OpenAIEmbeddings(
            model=m.model_name,
            api_key=SecretStr(decrypt_secret(m.api_key_enc) or "dummy"),
            base_url=m.api_base.rstrip("/") if m.api_base else None,
            dimensions=m.dim,
            chunk_size=m.request_size,
            check_embedding_ctx_length=False,
            http_client=sync_client(m.api_base, 30),
        )
        vec = client.embed_query("连通测试")
    except Exception as e:  # noqa: BLE001 测试接口要把失败原因如实返回
        return {"ok": False, "error": str(e)[:300], "dim": None}
    if len(vec) != m.dim:
        return {"ok": False, "dim": len(vec),
                "error": f"返回维度 {len(vec)} 与配置的 {m.dim} 不一致，入库会失败"}
    return {"ok": True, "dim": len(vec), "reply": f"已连通，返回 {len(vec)} 维向量"}


def options(db: Session) -> list:
    """建库下拉的候选：只列启用的，带维度与描述性标签。

    没有候选时返回空数组而不是抛错：前端据此提示"先去配一个向量模型"。
    """
    rows = db.query(EmbeddingModel).filter(EmbeddingModel.is_enabled.is_(True)).order_by(EmbeddingModel.id).all()
    return [{"id": m.id, "name": m.name, "provider": m.provider, "model_name": m.model_name, "dim": m.dim} for m in rows]


def spec_for_kb(db: Session, kb: KnowledgeBase) -> embeddings.EmbeddingSpec:
    """知识库 → 向量化配置。入库与检索都用它，保证一次操作内前后端用的是同一个模型。

    模型行缺失（被删 / 停用）时抛 BizError：入库要明确失败并提示，
    而不是悄悄退回全局配置把数据用错误的模型向量化。
    """
    m = db.get(EmbeddingModel, kb.embedding_model_id)
    if m is None:
        raise BizError(400, f"知识库「{kb.name}」绑定的向量模型不存在（id={kb.embedding_model_id}），请重新配置")
    if not m.is_enabled:
        raise BizError(400, f"知识库「{kb.name}」绑定的向量模型「{m.name}」已停用")
    return embeddings.spec_from_row(m)
