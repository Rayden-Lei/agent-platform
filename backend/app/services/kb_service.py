import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.db.models import Document, DocumentChunk, KnowledgeBase
from app.rag.minio_client import upload_file
from app.rag.retriever import retrieve


def list_kbs(db: Session) -> list[dict]:
    rows = db.query(KnowledgeBase).order_by(KnowledgeBase.id).all()
    return [{"id": k.id, "name": k.name, "description": k.description, "chunk_size": k.chunk_size, "chunk_overlap": k.chunk_overlap} for k in rows]


def create_kb(db: Session, data, user) -> dict:
    kb = KnowledgeBase(
        name=data.name,
        description=data.description,
        embedding_model=data.embedding_model,
        chunk_size=data.chunk_size,
        chunk_overlap=data.chunk_overlap,
        created_by=user.id,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return {"id": kb.id, "name": kb.name, "description": kb.description}


def get_kb(db: Session, kb_id: int) -> KnowledgeBase:
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise BizError(404, "知识库不存在")
    return kb


def get_kb_detail(db: Session, kb_id: int) -> dict:
    kb = get_kb(db, kb_id)
    return {"id": kb.id, "name": kb.name, "description": kb.description, "chunk_size": kb.chunk_size, "chunk_overlap": kb.chunk_overlap}


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


def list_documents(db: Session, kb_id: int) -> list[dict]:
    get_kb(db, kb_id)
    rows = db.query(Document).filter(Document.kb_id == kb_id).order_by(Document.id.desc()).all()
    return [{"id": d.id, "name": d.name, "file_type": d.file_type, "status": d.status, "chunk_count": d.chunk_count, "error": d.error} for d in rows]


def delete_document(db: Session, kb_id: int, doc_id: int) -> None:
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise BizError(404, "文档不存在")
    db.delete(doc)
    db.commit()


def search_kb(db: Session, kb_id: int, query: str, top_k: int) -> dict:
    get_kb(db, kb_id)
    return {"items": retrieve(kb_id, query, top_k)}
