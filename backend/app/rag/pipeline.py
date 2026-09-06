"""文档入库流水线：下载 → 解析 → 分片 → 向量化 → 写切片（含权限标签与向量后端快照）。

单篇文档的完整处理链在 process_document 中串起，任一阶段失败统一落 doc.error 并置 failed。
"""
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.config import settings
from app.db.models import Document, DocumentChunk, KnowledgeBase
from app.db.session import SessionLocal
from app.rag.embeddings import embed_texts_detailed
from app.rag.minio_client import download_file
from app.rag.parser import parse_document

logger = logging.getLogger(__name__)

_CN_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
# 表格行里字段之间的分隔（与 parser.parse_table 一致）
_FIELD_SEP = " | "
# 向量化 + 写库按此批量推进并逐批提交：几万行的表格不能攒到最后一次 commit（内存、失败回滚、看不到进度）
INGEST_BATCH_SIZE = 100
# 文档处理的并发闸门：多篇同时上传时按 INGEST_CONCURRENCY 排队处理（默认串行），等待中的文档状态仍是 uploading
_ingest_slots: threading.Semaphore | None = None
_ingest_slots_lock = threading.Lock()


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


def process_document(doc_id: int) -> None:
    """后台处理一篇文档：下载 → 解析 → 分片 → 向量化 → 入库。失败落 doc.error 并记日志。多篇排队时按 INGEST_CONCURRENCY 串行。"""
    slot = _ingest_slot()
    if not slot.acquire(blocking=False):
        logger.info("文档 %s 排队等待处理（前面还有文档在向量化）", doc_id)
        slot.acquire()
    try:
        _process_document(doc_id)
    finally:
        slot.release()


def _process_document(doc_id: int) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if doc is None:
            logger.warning("文档处理跳过：文档 %s 不存在", doc_id)
            return
        kb = db.get(KnowledgeBase, doc.kb_id)
        doc.status = "parsing"
        db.commit()

        with tempfile.TemporaryDirectory() as tmp:
            local_path = os.path.join(tmp, doc.name)
            download_file(doc.file_path, local_path)
            segments = parse_document(local_path, doc.file_type)

            doc.status = "chunking"
            db.commit()

            chunks = chunk_segments(segments, doc.file_type, kb.chunk_size or 500, kb.chunk_overlap or 50)
            # 计划总数与开始时间先落库：前端据此显示百分比、速度与预计剩余
            doc.chunk_total = len(chunks)
            doc.processing_started_at = datetime.now(timezone.utc)
            db.commit()
            if not chunks:
                doc.status = "ready"
                doc.chunk_count = 0
                doc.error = None
                doc.finished_at = datetime.now(timezone.utc)
                db.commit()
                logger.info("文档 %s 解析后无有效切片，标记为 ready", doc_id)
                return

            # 逐批向量化并提交：chunk_count 随批推进，列表页能看到进度；中途失败已提交的批不丢，重新解析时整体清掉
            degraded_models: set = set()
            for start in range(0, len(chunks), INGEST_BATCH_SIZE):
                batch = chunks[start:start + INGEST_BATCH_SIZE]
                embedded = embed_texts_detailed([c["content"] for c in batch])
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
                db.commit()
                if (start // INGEST_BATCH_SIZE) % 20 == 19:
                    logger.info("文档 %s 入库进度 %d / %d", doc_id, doc.chunk_count, len(chunks))
            if degraded_models:
                # 降级入库的切片检索质量不如真实向量，meta 里记下来，排查"检索不准"时能立刻定位
                logger.warning("文档 %s 有切片使用 %s 向量入库（降级）", doc_id, "/".join(sorted(degraded_models)))

            doc.status = "ready"
            doc.error = None
            doc.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("文档 %s 处理完成：%d 个切片，向量后端 %s", doc_id, len(chunks), "/".join(sorted(degraded_models)) if degraded_models else "model")
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
