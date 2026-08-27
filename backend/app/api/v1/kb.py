import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import Document, DocumentChunk, KnowledgeBase, User
from app.db.session import get_db
from app.rag.minio_client import upload_file
from app.rag.pipeline import process_document
from app.rag.retriever import retrieve

router = APIRouter(prefix="/knowledge-bases", tags=["kb"])


class KnowledgeBaseIn(BaseModel):
    name: str
    description: str = ""
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 500
    chunk_overlap: int = 50


class SearchIn(BaseModel):
    query: str
    top_k: int = 4


@router.get("")
def list_kbs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(KnowledgeBase).order_by(KnowledgeBase.id).all()
    return [{"id": k.id, "name": k.name, "description": k.description, "chunk_size": k.chunk_size, "chunk_overlap": k.chunk_overlap} for k in rows]


@router.post("")
def create_kb(data: KnowledgeBaseIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
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


@router.get("/{kb_id}")
def get_kb(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"id": kb.id, "name": kb.name, "description": kb.description, "chunk_size": kb.chunk_size, "chunk_overlap": kb.chunk_overlap}


@router.delete("/{kb_id}")
def delete_kb(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    db.query(DocumentChunk).filter(DocumentChunk.kb_id == kb_id).delete()
    db.query(Document).filter(Document.kb_id == kb_id).delete()
    db.delete(kb)
    db.commit()
    return {"code": 0, "message": "ok"}


@router.post("/{kb_id}/documents")
async def upload_document(
    kb_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    content = await file.read()
    filename = file.filename or "unnamed"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    object_name = f"{uuid.uuid4().hex}_{filename}"
    upload_file(object_name, content, file.content_type or "application/octet-stream")

    doc = Document(kb_id=kb_id, name=filename, file_path=object_name, file_type=ext, status="uploading")
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background_tasks.add_task(process_document, doc.id)
    return {"id": doc.id, "kb_id": kb_id, "name": filename, "file_type": ext, "status": doc.status}


@router.get("/{kb_id}/documents")
def list_documents(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(Document).filter(Document.kb_id == kb_id).order_by(Document.id.desc()).all()
    return [{"id": d.id, "name": d.name, "file_type": d.file_type, "status": d.status, "chunk_count": d.chunk_count, "error": d.error} for d in rows]


@router.delete("/{kb_id}/documents/{doc_id}")
def delete_document(kb_id: int, doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).delete()
    db.delete(doc)
    db.commit()
    return {"code": 0, "message": "ok"}


@router.post("/{kb_id}/search")
def search(kb_id: int, data: SearchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    items = retrieve(kb_id, data.query, data.top_k)
    return {"items": items}
