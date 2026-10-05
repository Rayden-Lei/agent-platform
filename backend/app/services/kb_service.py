import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_, true
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.models import Agent, AgentVersion, AuditLog, Document, DocumentChunk, KnowledgeBase, User
from app.rag.minio_client import upload_file
from app.rag.retriever import kb_allows, retrieve, retrieve_with_stats

SORTABLE = {"id": KnowledgeBase.id, "name": KnowledgeBase.name, "updated_at": KnowledgeBase.updated_at}
DOC_SORTABLE = {"id": Document.id, "name": Document.name, "status": Document.status, "chunk_count": Document.chunk_count, "created_at": Document.created_at}
DOC_STATUSES = ("uploading", "parsing", "chunking", "ready", "failed")
# 允许上传的扩展名：与 rag/parser.parse_document 能解析的一致（docs/15 KB-03，2026-09-29 前不校验）
UPLOAD_EXTENSIONS = ("txt", "md", "markdown", "pdf", "docx", "csv", "xlsx", "png", "jpg", "jpeg", "webp", "bmp")
FILENAME_MAX_CHARS = 200
# 访问权限页签逐个说明"谁能检索"的身份；None 是匿名访客（1C 的分享链接，检索时 role 为空）
ACCESS_ROLES = {"admin": "admin", "developer": "developer", "caller": "caller", "anonymous": None}
ACCESS_LOG_ACTIONS = ("create", "update_access")


def visible_kb_filter(role: str | None):
    """管理面的知识库可见性（docs/15 KB-01）：与检索闸门 retriever.kb_allows 同一口径 —— admin 全部；
    其他角色为公开库，或 visible_roles 含本角色。列表、详情、文档、切片、上传、检索、批量统一套用，不可见一律 404。"""
    if role == "admin":
        return true()
    conditions = [KnowledgeBase.is_public.is_(True)]
    if role:
        conditions.append(KnowledgeBase.visible_roles.contains([role]))
    return or_(*conditions)


def _check_not_shut_out(role: str, is_public: bool, visible_roles: list) -> None:
    """非 admin 保存的权限必须仍包含自己（docs/15 KB-01）：否则一保存自己就看不到这个库、也改不回来。"""
    if role != "admin" and not is_public and role not in (visible_roles or []):
        raise BizError(400, "不能把自己的角色排除在可见范围外：保存后你将无法再看到、也改不回这个知识库")


def _policy(is_public: bool, visible_roles: list | None) -> dict:
    return {"is_public": bool(is_public), "visible_roles": list(visible_roles or [])}


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


def list_kbs(db: Session, user: User, params: PageParams, q: str = None, is_public: bool = None, sort: SortParams = None) -> dict:
    """分页列出当前用户可见的知识库：q 名称模糊，可按公开 / 受限过滤，白名单排序；附文档与切片统计。"""
    query = db.query(KnowledgeBase).filter(visible_kb_filter(user.role))
    if q:
        query = query.filter(KnowledgeBase.name.ilike(f"%{q}%"))
    if is_public is not None:
        query = query.filter(KnowledgeBase.is_public.is_(is_public))
    page = paginate(apply_sort(query, sort, SORTABLE, [KnowledgeBase.id.asc()]), params)
    page["items"] = _serialize(db, page["items"])
    return page


def create_kb(db: Session, data, user) -> dict:
    """新建知识库，记录创建人；权限字段是初始权限（之后在访问权限页签改，update_access），非 admin 不能把自己排除在外。写审计 create。"""
    _check_not_shut_out(user.role, data.is_public, data.visible_roles)
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
    db.flush()
    record_audit(db, user, "create", "knowledge_base", kb.id, detail={"name": kb.name, **_policy(kb.is_public, kb.visible_roles)})
    db.refresh(kb)
    return _serialize(db, [kb])[0]


def get_kb(db: Session, kb_id: int, role: str | None) -> KnowledgeBase:
    """按 ID 取该角色可见的知识库：不存在与不可见都是 404「知识库不存在」，不暴露受限库是否存在（docs/15 KB-01）。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id, visible_kb_filter(role)).first()
    if kb is None:
        raise BizError(404, "知识库不存在")
    return kb


def _bound_agents(db: Session, kb_id: int) -> list[dict]:
    """绑定本库的智能体：草稿绑定，或在线智能体的线上版本绑定（与 agent_service.agent_ids_using_models 同一口径）。
    in_live 供访问权限页签判断"已发布、绑定本库、调用者却检索不到"；2026-10-05 前只看草稿，线上绑定而草稿已解绑的漏掉。各一次查询。"""
    draft_ids = {i for (i,) in db.query(Agent.id).filter(Agent.kb_ids.contains([kb_id]))}
    live_ids = {i for (i,) in (
        db.query(Agent.id)
        .join(AgentVersion, (AgentVersion.agent_id == Agent.id) & (AgentVersion.version == Agent.published_version))
        .filter(Agent.status == "published", AgentVersion.snapshot["kb_ids"].contains([kb_id]))
    )}
    ids = draft_ids | live_ids
    if not ids:
        return []
    rows = db.query(Agent.id, Agent.name, Agent.status).filter(Agent.id.in_(ids)).order_by(Agent.id)
    return [{"id": i, "name": n, "status": s, "in_draft": i in draft_ids, "in_live": i in live_ids} for i, n, s in rows]


def get_kb_detail(db: Session, kb_id: int, user: User) -> dict:
    """详情：基础字段 + 统计 + 绑定它的智能体 + 各身份能否检索（access，由检索闸门 kb_allows 算，前端不另写规则）。"""
    kb = get_kb(db, kb_id, user.role)
    access = {name: kb_allows(role, kb) for name, role in ACCESS_ROLES.items()}
    return {**_serialize(db, [kb])[0], "agents": _bound_agents(db, kb_id), "access": access}


def update_kb(db: Session, kb_id: int, data, user: User) -> dict:
    """更新知识库的名称、描述与切片参数（切片参数只影响之后上传的文档）。权限不在这里改，走 update_access（docs/15 KB-01）。
    有改动才写审计 update，detail 只记改了哪些字段。"""
    kb = get_kb(db, kb_id, user.role)
    fields = ("name", "description", "chunk_size", "chunk_overlap")
    changed = [f for f in fields if getattr(kb, f) != getattr(data, f)]
    for f in changed:
        setattr(kb, f, getattr(data, f))
    if changed:
        record_audit(db, user, "update", "knowledge_base", kb.id, detail={"name": kb.name, "changed": changed})
    else:
        db.commit()
    db.refresh(kb)
    return _serialize(db, [kb])[0]


def update_access(db: Session, kb_id: int, data, user: User) -> dict:
    """改访问权限：改完立即生效（检索按本行当前的 is_public / visible_roles 鉴权，不读切片快照，已入库的切片不用重新解析）。
    非 admin 不能把自己排除在外（400）。有变化时 policy_version +1（切片 meta 记的是入库时的版本，据此能看出快照已过期），
    并写审计 update_access，detail 记改前改后；没变化原样返回、不写审计。"""
    kb = get_kb(db, kb_id, user.role)
    _check_not_shut_out(user.role, data.is_public, data.visible_roles)
    before, after = _policy(kb.is_public, kb.visible_roles), _policy(data.is_public, data.visible_roles)
    if before != after:
        kb.is_public = after["is_public"]
        kb.visible_roles = after["visible_roles"]
        kb.policy_version = (kb.policy_version or 1) + 1
        record_audit(db, user, "update_access", "knowledge_base", kb.id, detail={"name": kb.name, "before": before, "after": after})
        db.refresh(kb)
    return get_kb_detail(db, kb_id, user)


def list_access_changes(db: Session, kb_id: int, user: User, params: PageParams) -> dict:
    """访问权限的变更记录：建库时的初始权限（create）与每次改权限（update_access），新的在前。
    审计接口只对 admin 开放，这里只给能看到这个库的人看本库的这两类记录，不带 IP。"""
    get_kb(db, kb_id, user.role)
    query = db.query(AuditLog).filter(AuditLog.resource == "knowledge_base", AuditLog.resource_id == kb_id,
                                      AuditLog.action.in_(ACCESS_LOG_ACTIONS)).order_by(AuditLog.id.desc())
    return paginate(query, params, _access_change)


def _access_change(a: AuditLog) -> dict:
    """审计行 → 变更记录。建库记录没有改前，detail 本身就是初始权限；改权限记录取 detail 的 before / after。"""
    detail = a.detail or {}
    if a.action == "create":
        before, after = None, _policy(detail.get("is_public", True), detail.get("visible_roles"))
    else:
        before, after = detail.get("before"), detail.get("after")
    return {"id": a.id, "action": a.action, "username": a.username,
            "created_at": a.created_at.isoformat() if a.created_at else None, "before": before, "after": after}


def delete_kb(db: Session, kb_id: int, user: User) -> None:
    """删除知识库，文档与切片由数据库外键 CASCADE 级联删除；写审计 delete（与删除同一次提交）。"""
    kb = get_kb(db, kb_id, user.role)
    db.delete(kb)
    record_audit(db, user, "delete", "knowledge_base", kb_id, detail={"name": kb.name})


def upload_policy() -> dict:
    """上传策略（前端 accept 与大小预检用，不在前端硬编码）。"""
    return {"extensions": list(UPLOAD_EXTENSIONS), "max_mb": settings.KB_UPLOAD_MAX_MB}


def upload_too_large() -> BizError:
    return BizError(413, f"文件超过 {settings.KB_UPLOAD_MAX_MB} MB 上限")


def safe_filename(filename: str | None) -> str:
    """上传的文件名只取最后一段（/ 与反斜杠都算分隔符），去掉控制字符，限长（保留扩展名）。
    2026-09-29 前原样入库并拼进处理时的本地路径，以 / 开头的名字能让文件写到临时目录之外（docs/15 2.3 第 14 条）。"""
    name = re.split(r"[\\/]", filename or "")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch) != "Cc").strip()
    if len(name) > FILENAME_MAX_CHARS:
        stem, dot, ext = name.rpartition(".")
        keep_ext = dot and 0 < len(ext) <= 10
        name = stem[: FILENAME_MAX_CHARS - len(ext) - 1] + "." + ext if keep_ext else name[:FILENAME_MAX_CHARS]
    return name or "unnamed"


def check_upload(db: Session, kb_id: int, user: User, filename: str | None, size: int | None) -> tuple[str, str]:
    """读文件内容之前的校验：知识库存在且可见（404）、文件名清洗、扩展名在白名单（400）、已知大小时先比上限（413）。
    返回 (清洗后的文件名, 扩展名)。.xls 单独提示：openpyxl 读不了老格式，此前上传后必然解析失败，不为它引入新依赖。"""
    get_kb(db, kb_id, user.role)
    name = safe_filename(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "xls":
        raise BizError(400, "不支持 .xls（老版 Excel），请另存为 .xlsx 后上传")
    if ext not in UPLOAD_EXTENSIONS:
        raise BizError(400, f"不支持的文件类型（{'.' + ext if ext else '没有扩展名'}），支持：{', '.join(UPLOAD_EXTENSIONS)}")
    if size is not None and size > settings.KB_UPLOAD_MAX_MB * 1024 * 1024:
        raise upload_too_large()
    return name, ext


def create_document(db: Session, kb_id: int, user: User, name: str, ext: str, content: bytes, content_type: str) -> Document:
    """上传文档：先落 MinIO（对象名带 uuid 前缀防重名），库记录初始为 uploading，由异步解析管道置 ready/failed。
    name / ext 须先经 check_upload 清洗与校验；空文件 400（解析出来什么都没有，只会留一篇失败的文档）。写审计 upload。"""
    if not content:
        raise BizError(400, "文件是空的")
    get_kb(db, kb_id, user.role)
    object_name = f"{uuid.uuid4().hex}_{name}"
    upload_file(object_name, content, content_type or "application/octet-stream")

    from app.rag.pipeline import NODE_NAME
    # 记下由本节点处理：共享库上另一台后端重启时不会来抢这篇
    doc = Document(kb_id=kb_id, name=name, file_path=object_name, file_type=ext, status="uploading", processing_node=NODE_NAME)
    db.add(doc)
    db.flush()
    _audit_document(db, user, "upload", doc)
    db.refresh(doc)
    return doc


def _audit_document(db: Session, user: User, action: str, doc: Document) -> None:
    """文档操作的审计（upload / delete / reprocess / resume）：detail 带所属知识库与文件名；连同调用方未提交的修改一起提交。"""
    record_audit(db, user, action, "document", doc.id, detail={"kb_id": doc.kb_id, "name": doc.name})


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


def list_documents(db: Session, kb_id: int, user: User, params: PageParams, status: str = None, q: str = None, file_type: str = None,
                   created_from: datetime = None, created_to: datetime = None, sort: SortParams = None) -> dict:
    """分页列出知识库内文档：状态 / 类型精确，名称模糊，上传时间区间，白名单排序（默认新上传在前）。"""
    get_kb(db, kb_id, user.role)
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


def _get_document(db: Session, kb_id: int, doc_id: int, role: str | None) -> Document:
    """取知识库内的文档：知识库须对该角色可见（否则 404「知识库不存在」），文档须属于该库（否则 404「文档不存在」）。"""
    get_kb(db, kb_id, role)
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise BizError(404, "文档不存在")
    return doc


def delete_document(db: Session, kb_id: int, doc_id: int, user: User) -> None:
    """删除文档（切片级联删除）；文档必须属于该知识库，否则按不存在处理。写审计 delete（与删除同一次提交）。"""
    doc = _get_document(db, kb_id, doc_id, user.role)
    db.delete(doc)
    _audit_document(db, user, "delete", doc)


def prepare_reprocess(db: Session, kb_id: int, doc_id: int, user: User) -> Document:
    """重新解析前的准备：只允许 ready / failed 的文档（处理中 400）；清掉旧切片与错误、状态回到 uploading。
    实际解析由路由放进后台任务（process_document），与首次上传同一条管道。写审计 reprocess。"""
    doc = _get_document(db, kb_id, doc_id, user.role)
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
    _audit_document(db, user, "reprocess", doc)
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


def prepare_resume(db: Session, kb_id: int, doc_id: int, user: User) -> Document:
    """续处理前的准备：失败的文档、或处理中但已无心跳（中断）的文档，接着已入库的片继续；正常处理中的 400。
    切片保留不动，由管道核对总数后决定接着做还是重来；状态回到 uploading 排队。写审计 resume。"""
    from app.rag.pipeline import NODE_NAME
    doc = _get_document(db, kb_id, doc_id, user.role)
    if doc.status == "ready":
        raise BizError(400, "文档已处理完成，如需重建请用重新解析")
    if doc.status != "failed" and not is_stalled(doc):
        raise BizError(400, "文档正在处理中，请稍后再试")
    doc.status = "uploading"
    doc.error = None
    doc.finished_at = None
    doc.processing_node = NODE_NAME
    doc.heartbeat_at = datetime.now(timezone.utc)
    _audit_document(db, user, "resume", doc)
    db.refresh(doc)
    return doc


def apply_document_batch_action(db: Session, kb_id: int, doc_id: int, action: str, user: User) -> Document | None:
    """文档批量操作的单条执行（delete / reprocess）；reprocess 返回准备好的文档供路由排队解析。"""
    if action == "delete":
        delete_document(db, kb_id, doc_id, user)
        return None
    return prepare_reprocess(db, kb_id, doc_id, user)


def list_document_chunks(db: Session, kb_id: int, doc_id: int, user: User, params: PageParams) -> dict:
    """分页列出文档切片，附带 doc_id / doc_name 供前端详情展示。"""
    doc = _get_document(db, kb_id, doc_id, user.role)
    query = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).order_by(DocumentChunk.id)
    page = paginate(query, params, lambda c: {"id": c.id, "content": c.content, "meta": c.meta or {}, "token_count": c.token_count})
    # 分页信封之外附带文档信息，前端抽屉标题要用；total 即切片总数
    return {**page, "doc_id": doc.id, "doc_name": doc.name}


def search_kb(db: Session, kb_id: int, user: User, query: str, top_k: int, debug: bool = False) -> dict:
    """检索评测：知识库须对当前角色可见（否则 404，2026-10-05 前是 200 + kb_denied），按当前角色检索；
    debug=True 返回检索统计（命中数 / 权限拦截数），否则只返回命中片段。"""
    get_kb(db, kb_id, user.role)
    if debug:
        return retrieve_with_stats(kb_id, query, top_k, role=user.role)
    return {"items": retrieve(kb_id, query, top_k, role=user.role)}
