"""文档入库流水线：下载 → 解析 → 分片 → 向量化 → 写切片（含权限标签与向量后端快照）。

单篇文档的完整处理链在 process_document 中串起，任一阶段失败统一落 doc.error 并置 failed。
"""
import logging
import os
import socket
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from sqlalchemy import func

from app.config import settings
from app.db.models import Document, DocumentChunk, KnowledgeBase
from app.db.session import SessionLocal
from app.rag.embeddings import embed_texts_detailed
from app.rag.minio_client import download_file
from app.rag.parser import parse_document
from app.services import settings_service

logger = logging.getLogger(__name__)

_CN_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
# 表格行里字段之间的分隔（与 parser.parse_table 一致）
_FIELD_SEP = " | "
# 向量化 + 写库按批推进并逐批提交（几万行的表格不能攒到最后一次 commit）；批大小、并发请求数、写库缓冲
# 都是运行时参数（settings_service.ingest_options，页面"导入设置"），每篇文档开始处理时读一次
# 本节点标识：共享库上本机与服务器各跑一个后端，文档只由创建它的节点处理与续处理
NODE_NAME = socket.gethostname()[:128]
# 文档处理的并发闸门：多篇同时上传时按 INGEST_CONCURRENCY 排队处理（默认串行），等待中的文档状态仍是 uploading
_ingest_slots: threading.Semaphore | None = None
_ingest_slots_lock = threading.Lock()
# 排队等待期间刷心跳的间隔（秒）：实际取它与 INGEST_STALL_SECONDS/3 的较小值，保证排队中的文档不会被判成"中断"
QUEUE_HEARTBEAT_SECONDS = 60


def _ingest_slot() -> threading.Semaphore:
    global _ingest_slots
    with _ingest_slots_lock:
        if _ingest_slots is None:
            _ingest_slots = threading.Semaphore(max(1, settings.INGEST_CONCURRENCY))
        return _ingest_slots


def _text_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    """通用递归分片器：分隔符按中文习惯配置（段落/句/逗号优先级，见 _CN_SEPARATORS）。"""
    return RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=_CN_SEPARATORS)


def chunk_segments(segments: list, file_type: str, chunk_size: int, chunk_overlap: int) -> list:
    """按文件类型对解析片段做差异化分片。"""
    ext = (file_type or "").lower().lstrip(".")
    chunks = []

    if ext in ("md", "markdown"):
        # Markdown：按标题层级分片，保留标题
        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
            strip_headers=False,
        )
        for seg in segments:
            try:
                for mc in splitter.split_text(seg["content"]):
                    chunks.append({"content": mc.page_content, "meta": {**seg["meta"], "headings": mc.metadata}})
            except Exception as e:
                # 标题结构异常（如代码块里的 # 导致解析失败）时退回通用切片，不影响整篇入库
                logger.warning("Markdown 按标题分片失败，退回通用切片：%s", e)
                for sc in _text_splitter(chunk_size, chunk_overlap).split_text(seg["content"]):
                    chunks.append({"content": sc, "meta": seg["meta"]})
    elif ext == "pdf":
        # PDF：按页再按段落切片，保留页码
        splitter = _text_splitter(chunk_size, chunk_overlap)
        for seg in segments:
            for sc in splitter.split_text(seg["content"]):
                chunks.append({"content": sc, "meta": seg["meta"]})
    elif ext == "docx":
        # Word：按段落切片，保留标题上下文
        splitter = _text_splitter(chunk_size, chunk_overlap)
        for seg in segments:
            for sc in splitter.split_text(seg["content"]):
                chunks.append({"content": sc, "meta": seg["meta"]})
    elif ext in ("csv", "xlsx", "xls"):
        # 表格：按行分片（每行一个语义单元，保留列名）；超长行按字段边界再切，每片带上首列作为行标识
        for seg in segments:
            chunks.extend(split_table_row(seg, chunk_size, chunk_overlap))
    elif ext in ("png", "jpg", "jpeg", "webp", "bmp"):
        # 图片：OCR 文字按段落切片
        splitter = _text_splitter(chunk_size, chunk_overlap)
        for seg in segments:
            for sc in splitter.split_text(seg["content"]):
                chunks.append({"content": sc, "meta": seg["meta"]})
    else:
        # 纯文本：通用段落切片
        splitter = _text_splitter(chunk_size, chunk_overlap)
        for seg in segments:
            for sc in splitter.split_text(seg["content"]):
                chunks.append({"content": sc, "meta": seg["meta"]})

    return [c for c in chunks if c["content"].strip()]


def split_table_row(seg: dict, chunk_size: int, chunk_overlap: int) -> list:
    """表格行超过 chunk_size 时按字段边界切成多片，每片都以首列（如"标题: 紫杉醇注射液"）开头，保证独立可读；
    单个字段就超长的（如说明书里的"注意事项"）再用通用分片器切，续片标 "字段名(续)"。meta 保留行号并加 part 序号。"""
    content = seg["content"]
    if len(content) <= chunk_size:
        return [{"content": content, "meta": seg["meta"]}]
    parts = content.split(_FIELD_SEP)
    key = parts[0]
    pieces: list = []
    group: list = []

    def flush():
        # 只剩行标识自己的组不单独成片（每片都会带上它）
        if group and group != [key]:
            body = _FIELD_SEP.join(group)
            pieces.append(body if body.startswith(key) else key + _FIELD_SEP + body)
        group.clear()

    budget = max(chunk_size - len(key) - len(_FIELD_SEP), chunk_size // 2)
    for part in parts:
        if len(part) > budget:
            flush()
            label, _, value = part.partition(": ")
            if not value:
                label, value = "内容", part
            for i, sub in enumerate(_text_splitter(budget - len(label) - 6, chunk_overlap).split_text(value)):
                pieces.append(f"{key}{_FIELD_SEP}{label}{'(续)' if i else ''}: {sub}")
            continue
        if group and len(_FIELD_SEP.join(group + [part])) > budget:
            flush()
        group.append(part)
    flush()
    if not pieces:
        return [{"content": content, "meta": seg["meta"]}]
    return [{"content": piece, "meta": {**seg["meta"], "part": n}} for n, piece in enumerate(pieces, start=1)]


def process_document(doc_id: int, resume: bool = False) -> None:
    """后台处理一篇文档：下载 → 解析 → 分片 → 向量化 → 入库。失败落 doc.error 并记日志。多篇排队时按 INGEST_CONCURRENCY 串行。

    resume=True 表示续处理：切片是确定性的，重新解析分片后若总数与上次一致，就从已入库的第 N 片接着向量化；
    总数不一致（切片参数改了）则清掉重来。
    """
    slot = _ingest_slot()
    if not slot.acquire(blocking=False):
        logger.info("文档 %s 排队等待处理（前面还有文档在向量化）", doc_id)
        # 等待期间定期刷心跳：排在一篇一小时的文档后面本来就要等很久，不刷会被前端和 prepare_resume 判成"中断"，
        # 用户点"继续处理"就会给同一篇再排一个任务，前一个做完后后一个发现切片已齐全反而清掉重做
        interval = min(QUEUE_HEARTBEAT_SECONDS, max(1, settings.INGEST_STALL_SECONDS / 3))
        _touch_heartbeat(doc_id)
        while not slot.acquire(timeout=interval):
            _touch_heartbeat(doc_id)
    try:
        _process_document(doc_id, resume)
    finally:
        slot.release()


def _touch_heartbeat(doc_id: int) -> None:
    """只刷新处理中文档的 heartbeat_at。刷不上不影响处理本身，记 WARN 后下一轮再试。"""
    db = SessionLocal()
    try:
        db.query(Document).filter(Document.id == doc_id, Document.status.in_(("uploading", "parsing", "chunking"))).update(
            {Document.heartbeat_at: datetime.now(timezone.utc)}, synchronize_session=False)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("文档 %s 排队心跳刷新失败：%s", doc_id, e)
    finally:
        db.close()


def resume_stalled_documents(schedule) -> list:
    """后端启动时找出**确实已经中断**的文档，逐篇交给 schedule 续处理。返回被续处理的文档 id 列表。

    两个条件缺一不可：
    1. `processing_node` 是本机 —— 共享库上另一台后端的文档不能抢；
    2. `heartbeat_at` 已经超过 `INGEST_STALL_SECONDS` 没更新 —— **同一台机器上可能还有别的进程正在处理它**
       （开发机上的另一个后端、pytest、脚本）。2026-09-06 就是漏了这条：跑测试时启动的进程把用户正在导入的文档
       抢过来按测试桩重新解析，删掉了一万九千片真实切片。心跳新鲜 = 有活着的进程在写，一律不碰。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.INGEST_STALL_SECONDS)
    db = SessionLocal()
    try:
        candidates = db.query(Document).filter(
            Document.status.in_(("uploading", "parsing", "chunking")),
            Document.processing_node == NODE_NAME,
        ).order_by(Document.id).all()
        stalled, alive = [], []
        for doc in candidates:
            last = doc.heartbeat_at or doc.processing_started_at or doc.created_at
            (stalled if last is None or last < cutoff else alive).append(doc.id)
    finally:
        db.close()
    if alive:
        logger.info("跳过 %d 篇心跳仍在更新的文档（另有进程正在处理）：%s", len(alive), alive)
    for doc_id in stalled:
        logger.warning("文档 %s 上次处理被中断（心跳停在 %s 秒前），启动后自动续处理", doc_id, settings.INGEST_STALL_SECONDS)
        schedule(doc_id)
    return stalled


def _resume_start(db, doc: Document, chunks: list, resume: bool) -> int:
    """算出本次从第几片开始：续处理且总数一致就接着已入库的数量；否则清掉已有切片从 0 开始。"""
    existing = db.query(func.count(DocumentChunk.id)).filter(DocumentChunk.doc_id == doc.id).scalar() or 0
    if resume and existing and doc.chunk_total == len(chunks) and existing < len(chunks):
        logger.info("文档 %s 续处理：已入库 %d / %d 片，从第 %d 片继续", doc.id, existing, len(chunks), existing)
        return existing
    if existing:
        if resume:
            logger.warning("文档 %s 无法续处理（切片总数 %s → %d 或已完成），清掉 %d 片重来", doc.id, doc.chunk_total, len(chunks), existing)
        db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc.id).delete(synchronize_session=False)
        db.commit()
    return 0


def _write_batch(db, doc: Document, kb: KnowledgeBase, start: int, batch: list, embedded, degraded_models: set) -> None:
    """把一批已向量化的切片写库并提交，chunk_count / heartbeat_at 随批推进（列表页据此显示进度）。"""
    if embedded.mode != "model":
        degraded_models.add(embedded.model)
    for offset, (chunk, emb) in enumerate(zip(batch, embedded.vectors)):
        db.add(DocumentChunk(
            doc_id=doc.id,
            kb_id=doc.kb_id,
            content=chunk["content"],
            embedding=emb,
            meta={
                **chunk["meta"],
                "index": start + offset,
                # chunk 级权限标签（冗余存权限真值快照，供检索过滤与审计）
                "kb_id": kb.id,
                "doc_id": doc.id,
                "is_public": kb.is_public,
                "visible_roles": list(kb.visible_roles or []),
                "policy_version": kb.policy_version or 1,
                # 实际使用的向量后端快照：换模型或降级后，能区分哪些切片需要重建索引
                "embedding_mode": embedded.mode,
                "embedding_model": embedded.model,
                "embedding_dim": embedded.dim,
            },
            token_count=max(1, len(chunk["content"])),
        ))
    doc.chunk_count = start + len(batch)
    doc.heartbeat_at = datetime.now(timezone.utc)
    db.commit()


def _embed_and_write(db, doc: Document, kb: KnowledgeBase, chunks: list, start_at: int, opts, degraded_models: set) -> int:
    """从第 start_at 片起按 opts 流水化入库，返回本次写入的切片数。

    线程池只做向量化（不碰 db）；主线程按提交顺序取最早的一批写库。窗口满了才等最早的一批，
    所以最多有 embed_concurrency + write_buffer 批在飞（内存有界：每批 batch_size 条向量）。
    任何一批写库失败：取消还没开始的批，已提交的批保留（续处理接着做），异常交给 _process_document 落 failed。
    """
    written = 0
    pending: deque = deque()
    max_inflight = opts.embed_concurrency + opts.write_buffer
    pool = ThreadPoolExecutor(max_workers=opts.embed_concurrency, thread_name_prefix=f"embed-{doc.id}")

    def _flush_oldest() -> None:
        nonlocal written
        start, batch, future = pending.popleft()
        _write_batch(db, doc, kb, start, batch, future.result(), degraded_models)
        written += len(batch)
        if (start // opts.batch_size) % 20 == 19:
            logger.info("文档 %s 入库进度 %d / %d", doc.id, doc.chunk_count, len(chunks))

    try:
        for start in range(start_at, len(chunks), opts.batch_size):
            batch = chunks[start:start + opts.batch_size]
            texts = [c["content"] for c in batch]
            pending.append((start, batch, pool.submit(embed_texts_detailed, texts, opts.embedding_request_size)))
            if len(pending) >= max_inflight:
                _flush_oldest()
        while pending:
            _flush_oldest()
    finally:
        # 正常结束时所有批都已完成，这里只是回收线程；失败时取消尚未开始的批，正在跑的几批算完即止
        pool.shutdown(wait=False, cancel_futures=True)
    return written


def _process_document(doc_id: int, resume: bool = False) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if doc is None:
            logger.warning("文档处理跳过：文档 %s 不存在", doc_id)
            return
        kb = db.get(KnowledgeBase, doc.kb_id)
        doc.status = "parsing"
        doc.processing_node = NODE_NAME
        doc.heartbeat_at = datetime.now(timezone.utc)
        db.commit()

        with tempfile.TemporaryDirectory() as tmp:
            local_path = os.path.join(tmp, doc.name)
            download_file(doc.file_path, local_path)
            segments = parse_document(local_path, doc.file_type)

            doc.status = "chunking"
            db.commit()

            chunks = chunk_segments(segments, doc.file_type, kb.chunk_size or 500, kb.chunk_overlap or 50)
            start_at = _resume_start(db, doc, chunks, resume)
            # 计划总数、起点与开始时间先落库：前端据此显示百分比、速度（按本次新增的片算）与预计剩余
            doc.chunk_total = len(chunks)
            doc.resume_offset = start_at
            doc.chunk_count = start_at
            doc.processing_started_at = datetime.now(timezone.utc)
            doc.heartbeat_at = doc.processing_started_at
            db.commit()
            if not chunks:
                doc.status = "ready"
                doc.chunk_count = 0
                doc.error = None
                doc.finished_at = datetime.now(timezone.utc)
                db.commit()
                logger.info("文档 %s 解析后无有效切片，标记为 ready", doc_id)
                return

            # 向量化与写库流水化：线程池按 embed_concurrency 并发请求向量服务，主线程按批的先后顺序写库提交。
            # 必须按顺序提交 —— 续处理靠"已入库的切片数"当起点，乱序提交会让这个数对不上实际缺口。
            # 同时在飞的批数 = 并发数 + 写库缓冲：写库慢时模型不停，模型慢时写库等；两者都为最小值即退化成原来的串行。
            opts = settings_service.ingest_options(db)
            degraded_models: set = set()
            started = time.perf_counter()
            written = _embed_and_write(db, doc, kb, chunks, start_at, opts, degraded_models)
            if degraded_models:
                # 降级入库的切片检索质量不如真实向量，meta 里记下来，排查"检索不准"时能立刻定位
                logger.warning("文档 %s 有切片使用 %s 向量入库（降级）", doc_id, "/".join(sorted(degraded_models)))

            doc.status = "ready"
            doc.error = None
            doc.finished_at = datetime.now(timezone.utc)
            db.commit()
            elapsed = max(time.perf_counter() - started, 1e-6)
            logger.info("文档 %s 处理完成：%d 个切片（本次入库 %d 片，%.1f 片/秒，并发 %d × 每请求 %d 条，批 %d，缓冲 %d），向量后端 %s",
                        doc_id, len(chunks), written, written / elapsed, opts.embed_concurrency, opts.embedding_request_size, opts.batch_size, opts.write_buffer,
                        "/".join(sorted(degraded_models)) if degraded_models else "model")
    except Exception as e:
        logger.exception("文档 %s 处理失败", doc_id)
        # 异常可能发生在 commit 中途，事务已不可用，必须先回滚再重新取一次文档写失败状态
        db.rollback()
        failed_doc = db.get(Document, doc_id)
        if failed_doc is not None:
            failed_doc.status = "failed"
            failed_doc.error = str(e)[:1000]
            failed_doc.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
