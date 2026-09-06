import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.models import Agent, Document, DocumentChunk, KnowledgeBase, User
from app.rag.minio_client import upload_file
from app.rag.retriever import retrieve, retrieve_with_stats

SORTABLE = {"id": KnowledgeBase.id, "name": KnowledgeBase.name, "updated_at": KnowledgeBase.updated_at}
DOC_SORTABLE = {"id": Document.id, "name": Document.name, "status": Document.status, "chunk_count": Document.chunk_count, "created_at": Document.created_at}
DOC_STATUSES = ("uploading", "parsing", "chunking", "ready", "failed")


def _kb_dict(k: KnowledgeBase, stats: dict | None = None, creator: str | None = None) -> dict:
    """知识库行 → 对外字典（含权限、向量模型、文档 / 切片统计、创建人）。"""
    return {
        "id": k.id, "name": k.name, "description": k.description, "embedding_model": k.embedding_model,
        "chunk_size": k.chunk_size, "chunk_overlap": k.chunk_overlap,
        "is_public": k.is_public, "visible_roles": k.visible_roles, "policy_version": k.policy_version,
        "created_by": k.created_by, "created_by_username": creator,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "updated_at": k.updated_at.isoformat() if k.updated_at else None,
        **(stats or _empty_stats()),
    }


def _empty_stats() -> dict:
    return {"document_count": 0, "ready_count": 0, "failed_count": 0, "processing_count": 0, "chunk_count": 0, "token_count": 0}


def _stats_by_kb(db: Session, kb_ids: set[int]) -> dict[int, dict]:
    """一批知识库的文档状态计数与切片数 / token 数：两条分组查询，不逐库查。"""
    if not kb_ids:
        return {}
    doc_rows = (
        db.query(
            Document.kb_id, func.count(Document.id),
            func.sum(case((Document.status == "ready", 1), else_=0)),
            func.sum(case((Document.status == "failed", 1), else_=0)),
            func.sum(case((Document.status.in_(("uploading", "parsing", "chunking")), 1), else_=0)),
        ).filter(Document.kb_id.in_(kb_ids)).group_by(Document.kb_id).all()
    )
    chunk_rows = db.query(DocumentChunk.kb_id, func.count(DocumentChunk.id), func.coalesce(func.sum(DocumentChunk.token_count), 0)).filter(DocumentChunk.kb_id.in_(kb_ids)).group_by(DocumentChunk.kb_id).all()
    stats = {kb_id: _empty_stats() for kb_id in kb_ids}
    for kb_id, total, ready, failed, processing in doc_rows:
        stats[kb_id].update(document_count=int(total), ready_count=int(ready or 0), failed_count=int(failed or 0), processing_count=int(processing or 0))
    for kb_id, chunks, tokens in chunk_rows:
        stats[kb_id].update(chunk_count=int(chunks), token_count=int(tokens or 0))
    return stats


def _serialize(db: Session, rows: list) -> list[dict]:
    stats = _stats_by_kb(db, {k.id for k in rows})
    creator_ids = {k.created_by for k in rows if k.created_by}
    creators = dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
    return [_kb_dict(k, stats.get(k.id), creators.get(k.created_by)) for k in rows]


def list_kbs(db: Session, params: PageParams, q: str = None, is_public: bool = None, sort: SortParams = None) -> dict:
    """分页列出知识库：q 名称模糊，可按公开 / 受限过滤，白名单排序；附文档与切片统计。"""
    query = db.query(KnowledgeBase)
    if q:
        query = query.filter(KnowledgeBase.name.ilike(f"%{q}%"))
    if is_public is not None:
        query = query.filter(KnowledgeBase.is_public.is_(is_public))
    page = paginate(apply_sort(query, sort, SORTABLE, [KnowledgeBase.id.asc()]), params)
    page["items"] = _serialize(db, page["items"])
    return page


def create_kb(db: Session, data, user) -> dict:
    """新建知识库，记录创建人；权限字段决定后续检索可见性。"""
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
    return _serialize(db, [kb])[0]


def get_kb(db: Session, kb_id: int) -> KnowledgeBase:
    """按 ID 取知识库，不存在抛 BizError(404)。"""
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise BizError(404, "知识库不存在")
    return kb


def get_kb_detail(db: Session, kb_id: int) -> dict:
    """详情：基础字段 + 统计 + 引用它的智能体清单。"""
    kb = get_kb(db, kb_id)
    agents = [{"id": a.id, "name": a.name, "status": a.status} for a in db.query(Agent).filter(Agent.kb_ids.contains([kb_id])).order_by(Agent.id).all()]
    return {**_serialize(db, [kb])[0], "agents": agents}


def update_kb(db: Session, kb_id: int, data) -> dict:
    """更新知识库：权限变更时 policy_version +1 使检索侧权限缓存失效。切片参数只影响之后上传的文档。"""
    kb = get_kb(db, kb_id)
    kb.name = data.name
    kb.description = data.description
    kb.chunk_size = data.chunk_size
    kb.chunk_overlap = data.chunk_overlap
    new_roles = data.visible_roles or []
    if data.is_public != kb.is_public or new_roles != (kb.visible_roles or []):
        kb.policy_version = (kb.policy_version or 1) + 1  # 权限变更 → 版本号 +1，缓存失效
    kb.is_public = data.is_public
    kb.visible_roles = new_roles
    db.commit()
    db.refresh(kb)
    return _serialize(db, [kb])[0]


def delete_kb(db: Session, kb_id: int) -> None:
    """删除知识库，文档与切片由数据库外键 CASCADE 级联删除。"""
    kb = get_kb(db, kb_id)
    # documents / document_chunks 由数据库外键 CASCADE 级联删除
    db.delete(kb)
    db.commit()


def create_document(db: Session, kb_id: int, filename: str, content: bytes, content_type: str) -> Document:
    """上传文档：先落 MinIO（对象名带 uuid 前缀防重名），库记录初始为 uploading，由异步解析管道置 ready/failed。"""
    get_kb(db, kb_id)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    object_name = f"{uuid.uuid4().hex}_{filename}"
    upload_file(object_name, content, content_type or "application/octet-stream")

    from app.rag.pipeline import NODE_NAME
    # 记下由本节点处理：共享库上另一台后端重启时不会来抢这篇
    doc = Document(kb_id=kb_id, name=filename, file_path=object_name, file_type=ext, status="uploading", processing_node=NODE_NAME)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _doc_dict(d: Document) -> dict:
    return {
        "id": d.id, "kb_id": d.kb_id, "name": d.name, "file_type": d.file_type, "status": d.status,
        "chunk_count": d.chunk_count, "chunk_total": d.chunk_total, "error": d.error,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        # 处理进度：前端按 chunk_count / chunk_total 算百分比，按 processing_started_at 算速度与剩余，按 finished_at 算总耗时
        "processing_started_at": d.processing_started_at.isoformat() if d.processing_started_at else None,
        "finished_at": d.finished_at.isoformat() if d.finished_at else None,
        "heartbeat_at": d.heartbeat_at.isoformat() if d.heartbeat_at else None,
        "resume_offset": d.resume_offset or 0,
        "processing_node": d.processing_node,
    }


def list_documents(db: Session, kb_id: int, params: PageParams, status: str = None, q: str = None, file_type: str = None,
                   created_from: datetime = None, created_to: datetime = None, sort: SortParams = None) -> dict:
    """分页列出知识库内文档：状态 / 类型精确，名称模糊，上传时间区间，白名单排序（默认新上传在前）。"""
    get_kb(db, kb_id)
    query = db.query(Document).filter(Document.kb_id == kb_id)
    if status:
        query = query.filter(Document.status == status)
    if q:
        query = query.filter(Document.name.ilike(f"%{q}%"))
    if file_type:
        query = query.filter(Document.file_type == file_type)
    if created_from is not None:
        query = query.filter(Document.created_at >= created_from)
    if created_to is not None:
        query = query.filter(Document.created_at < created_to)
    return paginate(apply_sort(query, sort, DOC_SORTABLE, [Document.id.desc()]), params, _doc_dict)


def _get_document(db: Session, kb_id: int, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise BizError(404, "文档不存在")
    return doc


def delete_document(db: Session, kb_id: int, doc_id: int) -> None:
    """删除文档（切片级联删除）；文档必须属于该知识库，否则按不存在处理。"""
    doc = _get_document(db, kb_id, doc_id)
    db.delete(doc)
    db.commit()


def prepare_reprocess(db: Session, kb_id: int, doc_id: int) -> Document:
    """重新解析前的准备：只允许 ready / failed 的文档（处理中 400）；清掉旧切片与错误、状态回到 uploading。
    实际解析由路由放进后台任务（process_document），与首次上传同一条管道。"""
    doc = _get_document(db, kb_id, doc_id)
    if doc.status not in ("ready", "failed"):
        raise BizError(400, "文档正在处理中，请稍后再试")
    db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc.id).delete(synchronize_session=False)
    doc.status = "uploading"
    doc.error = None
    doc.chunk_count = 0
    doc.chunk_total = None
    doc.processing_started_at = None
    doc.finished_at = None
    doc.heartbeat_at = None
    doc.resume_offset = 0
    db.commit()
    db.refresh(doc)
    return doc


def is_stalled(doc: Document, now: datetime | None = None) -> bool:
    """处理中但超过 INGEST_STALL_SECONDS 没有心跳：多半是后端被杀或向量服务卡死。"""
    if doc.status not in ("uploading", "parsing", "chunking"):
        return False
    last = doc.heartbeat_at or doc.processing_started_at or doc.created_at
    if last is None:
        return True
    return (now or datetime.now(timezone.utc)) - last > timedelta(seconds=settings.INGEST_STALL_SECONDS)


def prepare_resume(db: Session, kb_id: int, doc_id: int) -> Document:
    """续处理前的准备：失败的文档、或处理中但已无心跳（中断）的文档，接着已入库的片继续；正常处理中的 400。
    切片保留不动，由管道核对总数后决定接着做还是重来；状态回到 uploading 排队。"""
    from app.rag.pipeline import NODE_NAME
    doc = _get_document(db, kb_id, doc_id)
    if doc.status == "ready":
        raise BizError(400, "文档已处理完成，如需重建请用重新解析")
    if doc.status != "failed" and not is_stalled(doc):
        raise BizError(400, "文档正在处理中，请稍后再试")
    doc.status = "uploading"
    doc.error = None
    doc.finished_at = None
    doc.processing_node = NODE_NAME
    doc.heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(doc)
    return doc


def apply_document_batch_action(db: Session, kb_id: int, doc_id: int, action: str) -> Document | None:
    """文档批量操作的单条执行（delete / reprocess）；reprocess 返回准备好的文档供路由排队解析。"""
    if action == "delete":
        delete_document(db, kb_id, doc_id)
        return None
    return prepare_reprocess(db, kb_id, doc_id)


def list_document_chunks(db: Session, kb_id: int, doc_id: int, params: PageParams) -> dict:
    """分页列出文档切片，附带 doc_id / doc_name 供前端详情展示。"""
    get_kb(db, kb_id)
    doc = _get_document(db, kb_id, doc_id)
    query = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).order_by(DocumentChunk.id)
    page = paginate(query, params, lambda c: {"id": c.id, "content": c.content, "meta": c.meta or {}, "token_count": c.token_count})
    # 分页信封之外附带文档信息，前端抽屉标题要用；total 即切片总数
    return {**page, "doc_id": doc.id, "doc_name": doc.name}


def search_kb(db: Session, kb_id: int, query: str, top_k: int, debug: bool = False, role: str = None) -> dict:
    """检索知识库：debug=True 返回检索统计（命中数/权限拦截数），否则只返回命中片段。"""
    get_kb(db, kb_id)
    if debug:
        return retrieve_with_stats(kb_id, query, top_k, role=role)
    return {"items": retrieve(kb_id, query, top_k, role=role)}
