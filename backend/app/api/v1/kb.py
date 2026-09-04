"""知识库（KB）路由：知识库 CRUD、文档上传 / 解析 / 分块查看、库内检索。

除检索接口把当前用户角色传给 service 做可见性过滤（ACL）外，其余接口仅允许
admin / developer 角色访问。文档解析在后台任务中异步执行。
"""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.rag.pipeline import process_document
from app.services import kb_service

router = APIRouter(prefix="/knowledge-bases", tags=["kb"])


class KnowledgeBaseIn(BaseModel):
    """创建 / 更新知识库的请求体：name 必填；embedding_model 指定向量化模型；
    chunk_size / chunk_overlap 为文档分块参数；is_public / visible_roles 控制可见范围。
    """

    name: str
    description: str = ""
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 500
    chunk_overlap: int = 50
    is_public: bool = True
    visible_roles: list[str] = []


class SearchIn(BaseModel):
    """知识库检索请求体：query 检索词，top_k 返回条数，debug 返回检索调试信息。"""

    query: str
    top_k: int = 4
    debug: bool = False


@router.get("")
def list_kbs(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """知识库列表（分页），支持名称模糊匹配。"""
    return kb_service.list_kbs(db, params, q)


@router.post("")
def create_kb(data: KnowledgeBaseIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建知识库。"""
    return kb_service.create_kb(db, data, user)


@router.get("/{kb_id}")
def get_kb(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询知识库详情。"""
    return kb_service.get_kb_detail(db, kb_id)


@router.put("/{kb_id}")
def update_kb(kb_id: int, data: KnowledgeBaseIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 更新知识库配置。"""
    return kb_service.update_kb(db, kb_id, data)


@router.delete("/{kb_id}")
def delete_kb(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 删除知识库。"""
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
    # 解析 / 分块 / 向量化放入后台任务异步执行，接口先返回文档记录，前端轮询 status
    background_tasks.add_task(process_document, doc.id)
    return {"id": doc.id, "kb_id": kb_id, "name": filename, "file_type": doc.file_type, "status": doc.status}


@router.get("/{kb_id}/documents")
def list_documents(
    kb_id: int,
    params: PageParams = Depends(page_params),
    status: Literal["uploading", "parsing", "chunking", "ready", "failed"] | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """知识库下的文档列表（分页），可按解析状态过滤。"""
    return kb_service.list_documents(db, kb_id, params, status)


@router.get("/{kb_id}/documents/{doc_id}/chunks")
def list_chunks(kb_id: int, doc_id: int, params: PageParams = Depends(page_params), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """指定文档的分块列表（分页），用于查看解析结果。"""
    return kb_service.list_document_chunks(db, kb_id, doc_id, params)


@router.delete("/{kb_id}/documents/{doc_id}")
def delete_document(kb_id: int, doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除指定文档及其分块。"""
    kb_service.delete_document(db, kb_id, doc_id)
    return {"code": 0, "message": "ok"}


@router.post("/{kb_id}/search")
def search(kb_id: int, data: SearchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """在知识库内检索。传入当前用户角色用于可见性过滤（ACL）。"""
    return kb_service.search_kb(db, kb_id, data.query, data.top_k, debug=data.debug, role=user.role)
