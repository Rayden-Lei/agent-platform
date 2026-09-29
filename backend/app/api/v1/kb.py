"""知识库（KB）路由：知识库 CRUD、文档上传 / 解析 / 重新解析 / 分块查看、批量操作、库内检索。

除检索接口把当前用户角色传给 service 做可见性过滤（ACL）外，其余接口仅允许
admin / developer 角色访问。文档解析在后台任务中异步执行。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params, time_range
from app.db.models import User
from app.db.session import get_db
from app.rag.pipeline import process_document
from app.services import kb_service

router = APIRouter(prefix="/knowledge-bases", tags=["kb"])

DocStatus = Literal["uploading", "parsing", "chunking", "ready", "failed"]


class KnowledgeBaseIn(BaseModel):
    """创建 / 更新知识库的请求体：name 必填；embedding_model 指定向量化模型；
    chunk_size / chunk_overlap 为文档分块参数；is_public / visible_roles 控制可见范围。
    取值范围 2026-09-29 起校验（422，docs/15 KB-03）：此前 chunk_overlap 大于 chunk_size、visible_roles 写错角色名都能存进去。
    """

    name: str = Field(min_length=1, max_length=128)
    description: str = Field("", max_length=2000)
    embedding_model: str = Field("text-embedding-3-small", max_length=128)
    chunk_size: int = Field(500, ge=50, le=5000)
    chunk_overlap: int = Field(50, ge=0, le=1000)
    is_public: bool = True
    visible_roles: list[Literal["admin", "developer", "caller"]] = []

    @model_validator(mode="after")
    def _overlap_below_size(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        return self


class SearchIn(BaseModel):
    """知识库检索请求体：query 检索词（1～1000 字），top_k 返回条数（1～50），debug 返回检索调试信息。"""

    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(4, ge=1, le=50)
    debug: bool = False


class KbBatchIn(BatchIn):
    action: Literal["delete"]


class DocumentBatchIn(BatchIn):
    action: Literal["delete", "reprocess"]


@router.get("")
def list_kbs(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    is_public: bool | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """知识库列表（分页），支持名称模糊、公开 / 受限过滤；sort 可选 id / name / updated_at；附文档与切片统计。"""
    return kb_service.list_kbs(db, params, q, is_public, sort)


@router.post("")
def create_kb(data: KnowledgeBaseIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建知识库。"""
    return kb_service.create_kb(db, data, user)


# 固定路径必须声明在 /{kb_id} 之前
@router.post("/batch")
def batch_kbs(data: KbBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量删除知识库：逐条独立执行并返回成功与失败清单。"""
    return run_batch(db, data.unique_ids(), lambda kb_id: kb_service.delete_kb(db, kb_id))


@router.get("/upload-policy")
def upload_policy(user: User = Depends(require_roles("admin", "developer"))):
    """上传策略：允许的扩展名与大小上限（MB）。前端据此设 accept 与上传前预检，不硬编码。"""
    return kb_service.upload_policy()


@router.get("/{kb_id}")
def get_kb(kb_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """知识库详情（含统计与引用它的智能体）。"""
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
    """上传文档（docs/04 4.8）：文件名只保留最后一段并清洗，扩展名须在上传策略的白名单内（400），
    超过 KB_UPLOAD_MAX_MB 413；这些都在写 MinIO、建文档行之前拒绝。"""
    name, ext = await run_in_threadpool(kb_service.check_upload, db, kb_id, file.filename, file.size)
    content = await _read_limited(file, settings.KB_UPLOAD_MAX_MB * 1024 * 1024)
    # 存 MinIO 是阻塞 IO（几十 MB 的文件走公网要几十秒），必须挪出事件循环 ——
    # 写在 async 路由里会占住整个进程：2026-09-06 一次上传卡了 436 秒，期间所有接口都不响应，页面看着像服务挂了
    doc = await run_in_threadpool(kb_service.create_document, db, kb_id, name, ext, content, file.content_type or "application/octet-stream")
    # 解析 / 分块 / 向量化放入后台任务异步执行，接口先返回文档记录，前端轮询 status
    background_tasks.add_task(process_document, doc.id)
    return {"id": doc.id, "kb_id": kb_id, "name": name, "file_type": doc.file_type, "status": doc.status}


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """分块读取并计数，超过上限 413。file.size 拿不到时（分块传输）也拦得住，不会先整块读进内存再判断。"""
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise kb_service.upload_too_large()
    return bytes(buf)


@router.get("/{kb_id}/documents")
def list_documents(
    kb_id: int,
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    status: DocStatus | None = Query(None),
    q: str | None = Query(None, max_length=128, description="文件名模糊匹配"),
    file_type: str | None = Query(None, max_length=16),
    created_from: datetime | None = Query(None),
    created_to: datetime | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """知识库下的文档列表（分页），可按状态、文件名、类型、上传时间区间过滤；sort 可选 id / name / status / chunk_count / created_at。"""
    created_from, created_to = time_range(created_from, created_to)
    return kb_service.list_documents(db, kb_id, params, status, q, file_type, created_from, created_to, sort)


# 固定路径必须声明在 /{doc_id} 之前
@router.post("/{kb_id}/documents/batch")
def batch_documents(kb_id: int, data: DocumentBatchIn, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量删除 / 重新解析文档：逐条独立执行；重新解析的文档排进后台任务。"""
    queued: list[int] = []

    def _apply(doc_id: int) -> None:
        doc = kb_service.apply_document_batch_action(db, kb_id, doc_id, data.action)
        if doc is not None:
            queued.append(doc.id)

    result = run_batch(db, data.unique_ids(), _apply)
    for doc_id in queued:
        background_tasks.add_task(process_document, doc_id)
    return result


@router.post("/{kb_id}/documents/{doc_id}/resume")
def resume_document(kb_id: int, doc_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """中断后继续处理：失败或已无心跳的处理中文档，从已入库的切片接着向量化（切片参数没变时不重来）；正常处理中 400。"""
    doc = kb_service.prepare_resume(db, kb_id, doc_id)
    background_tasks.add_task(process_document, doc.id, True)
    return {"id": doc.id, "status": doc.status, "chunk_count": doc.chunk_count, "chunk_total": doc.chunk_total}


@router.post("/{kb_id}/documents/{doc_id}/reprocess")
def reprocess_document(kb_id: int, doc_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """重新解析文档（失败的文档重试，或切片参数改了之后重建）：清掉旧切片后排进后台任务；处理中的文档 400。"""
    doc = kb_service.prepare_reprocess(db, kb_id, doc_id)
    background_tasks.add_task(process_document, doc.id)
    return {"id": doc.id, "status": doc.status}


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
