import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import Document, DocumentChunk, KnowledgeBase
from app.rag.minio_client import upload_file
from app.rag.retriever import retrieve, retrieve_with_stats


def _kb_dict(k: KnowledgeBase) -> dict:
    return {"id": k.id, "name": k.name, "description": k.description, "chunk_size": k.chunk_size, "chunk_overlap": k.chunk_overlap, "is_public": k.is_public, "visible_roles": k.visible_roles}


def list_kbs(db: Session, params: PageParams, q: str = None) -> dict:
    query = db.query(KnowledgeBase)
    if q:
        query = query.filter(KnowledgeBase.name.ilike(f"%{q}%"))
    return paginate(query.order_by(KnowledgeBase.id), params, _kb_dict)


def create_kb(db: Session, data, user) -> dict:
    kb = KnowledgeBase(
        name=data.name,
        description=data.description,
        embedding_model=data.embedding_model,
        chunk_size=data.chunk_size,
        chunk_overlap=data.chunk_overlap,
        is_public=data.is_public,
        visible_roles=data.visible_roles or [],
        created_by=user.id,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return {"id": kb.id, "name": kb.name, "description": kb.description, "is_public": kb.is_public, "visible_roles": kb.visible_roles}


def get_kb(db: Session, kb_id: int) -> KnowledgeBase:
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise BizError(404, "知识库不存在")
    return kb


def get_kb_detail(db: Session, kb_id: int) -> dict:
    kb = get_kb(db, kb_id)
    return {"id": kb.id, "name": kb.name, "description": kb.description, "chunk_size": kb.chunk_size, "chunk_overlap": kb.chunk_overlap, "is_public": kb.is_public, "visible_roles": kb.visible_roles}


def update_kb(db: Session, kb_id: int, data) -> dict:
    kb = get_kb(db, kb_id)
    kb.name = data.name
    kb.description = data.description
    new_roles = data.visible_roles or []
    if data.is_public != kb.is_public or new_roles != (kb.visible_roles or []):
        kb.policy_version = (kb.policy_version or 1) + 1  # 权限变更 → 版本号 +1，缓存失效
    kb.is_public = data.is_public
    kb.visible_roles = new_roles
    db.commit()
    db.refresh(kb)
    return {"id": kb.id, "name": kb.name, "description": kb.description, "is_public": kb.is_public, "visible_roles": kb.visible_roles, "policy_version": kb.policy_version}


def delete_kb(db: Session, kb_id: int) -> None:
    kb = get_kb(db, kb_id)
    # documents / document_chunks 由数据库外键 CASCADE 级联删除
    db.delete(kb)
    db.commit()


def create_document(db: Session, kb_id: int, filename: str, content: bytes, content_type: str) -> Document:
    get_kb(db, kb_id)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    object_name = f"{uuid.uuid4().hex}_{filename}"
    upload_file(object_name, content, content_type or "application/octet-stream")

    doc = Document(kb_id=kb_id, name=filename, file_path=object_name, file_type=ext, status="uploading")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def list_documents(db: Session, kb_id: int, params: PageParams, status: str = None) -> dict:
    get_kb(db, kb_id)
    query = db.query(Document).filter(Document.kb_id == kb_id)
    if status:
        query = query.filter(Document.status == status)
    return paginate(query.order_by(Document.id.desc()), params, lambda d: {
        "id": d.id, "name": d.name, "file_type": d.file_type, "status": d.status, "chunk_count": d.chunk_count, "error": d.error,
    })


def delete_document(db: Session, kb_id: int, doc_id: int) -> None:
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise BizError(404, "文档不存在")
    db.delete(doc)
    db.commit()


def list_document_chunks(db: Session, kb_id: int, doc_id: int, params: PageParams) -> dict:
    get_kb(db, kb_id)
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise BizError(404, "文档不存在")
    query = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).order_by(DocumentChunk.id)
    page = paginate(query, params, lambda c: {"id": c.id, "content": c.content, "meta": c.meta or {}, "token_count": c.token_count})
    # 分页信封之外附带文档信息，前端抽屉标题要用；total 即切片总数
    return {**page, "doc_id": doc.id, "doc_name": doc.name}


def search_kb(db: Session, kb_id: int, query: str, top_k: int, debug: bool = False, role: str = None) -> dict:
    get_kb(db, kb_id)
    if debug:
        return retrieve_with_stats(kb_id, query, top_k, role=role)
    return {"items": retrieve(kb_id, query, top_k, role=role)}
