from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.rag.pipeline import process_document
from app.services import kb_service

router = APIRouter(prefix="/knowledge-bases", tags=["kb"])


class KnowledgeBaseIn(BaseModel):
    name: str
    description: str = ""
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 500
    chunk_overlap: int = 50
    is_public: bool = True
    visible_roles: list[str] = []


class SearchIn(BaseModel):
    query: str
    top_k: int = 4
    debug: bool = False


@router.get("")
def list_kbs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return kb_service.list_kbs(db)


@router.post("")
def create_kb(data: KnowledgeBaseIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return kb_service.create_kb(db, data, user)


@router.get("/{kb_id}")
def get_kb(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return kb_service.get_kb_detail(db, kb_id)


@router.put("/{kb_id}")
def update_kb(kb_id: int, data: KnowledgeBaseIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return kb_service.update_kb(db, kb_id, data)


@router.delete("/{kb_id}")
def delete_kb(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    kb_service.delete_kb(db, kb_id)
    return {"code": 0, "message": "ok"}


@router.post("/{kb_id}/documents")
async def upload_document(
    kb_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    content = await file.read()
    filename = file.filename or "unnamed"
    doc = kb_service.create_document(db, kb_id, filename, content, file.content_type or "application/octet-stream")
    background_tasks.add_task(process_document, doc.id)
    return {"id": doc.id, "kb_id": kb_id, "name": filename, "file_type": doc.file_type, "status": doc.status}


@router.get("/{kb_id}/documents")
def list_documents(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return kb_service.list_documents(db, kb_id)


@router.get("/{kb_id}/documents/{doc_id}/chunks")
def list_chunks(kb_id: int, doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return kb_service.list_document_chunks(db, kb_id, doc_id)


@router.delete("/{kb_id}/documents/{doc_id}")
def delete_document(kb_id: int, doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    kb_service.delete_document(db, kb_id, doc_id)
    return {"code": 0, "message": "ok"}


@router.post("/{kb_id}/search")
def search(kb_id: int, data: SearchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return kb_service.search_kb(db, kb_id, data.query, data.top_k, debug=data.debug, role=user.role)
