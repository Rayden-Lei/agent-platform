"""文档入库流水线：下载 → 解析 → 分片 → 向量化 → 写切片（含权限标签与向量后端快照）。

单篇文档的完整处理链在 process_document 中串起，任一阶段失败统一落 doc.error 并置 failed。
"""
import logging
import os
import tempfile

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.db.models import Document, DocumentChunk, KnowledgeBase
from app.db.session import SessionLocal
from app.rag.embeddings import embed_texts_detailed
from app.rag.minio_client import download_file
from app.rag.parser import parse_document

logger = logging.getLogger(__name__)

_CN_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


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
        # 表格：按行分片（每行一个语义单元，保留列名）
        for seg in segments:
            chunks.append({"content": seg["content"], "meta": seg["meta"]})
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


def process_document(doc_id: int) -> None:
    """后台处理一篇文档：下载 → 解析 → 分片 → 向量化 → 入库。失败落 doc.error 并记日志。"""
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
            if not chunks:
                doc.status = "ready"
                doc.chunk_count = 0
                doc.error = None
                db.commit()
                logger.info("文档 %s 解析后无有效切片，标记为 ready", doc_id)
                return

            embedded = embed_texts_detailed([c["content"] for c in chunks])
            if embedded.mode != "model":
                # 降级入库的切片检索质量不如真实向量，meta 里记下来，排查"检索不准"时能立刻定位
                logger.warning("文档 %s 使用 %s 向量入库（降级）", doc_id, embedded.model)

            for i, (chunk, emb) in enumerate(zip(chunks, embedded.vectors)):
                db.add(DocumentChunk(
                    doc_id=doc.id,
                    kb_id=doc.kb_id,
                    content=chunk["content"],
                    embedding=emb,
                    meta={
                        **chunk["meta"],
                        "index": i,
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

            doc.chunk_count = len(chunks)
            doc.status = "ready"
            doc.error = None
            db.commit()
            logger.info("文档 %s 处理完成：%d 个切片，向量后端 %s", doc_id, len(chunks), embedded.model)
    except Exception as e:
        logger.exception("文档 %s 处理失败", doc_id)
        # 异常可能发生在 commit 中途，事务已不可用，必须先回滚再重新取一次文档写失败状态
        db.rollback()
        failed_doc = db.get(Document, doc_id)
        if failed_doc is not None:
            failed_doc.status = "failed"
            failed_doc.error = str(e)[:1000]
            db.commit()
    finally:
        db.close()
