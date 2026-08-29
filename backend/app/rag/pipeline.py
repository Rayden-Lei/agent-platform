import os
import tempfile

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.db.models import Document, DocumentChunk, KnowledgeBase
from app.db.session import SessionLocal
from app.rag.embeddings import embed_texts
from app.rag.minio_client import download_file
from app.rag.parser import parse_document

_CN_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


def _text_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
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
            except Exception:
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
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if doc is None:
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
                db.commit()
                return

            embeddings = embed_texts([c["content"] for c in chunks])

            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                db.add(DocumentChunk(
                    doc_id=doc.id,
                    kb_id=doc.kb_id,
                    content=chunk["content"],
                    embedding=emb,
                    meta={**chunk["meta"], "index": i},
                    token_count=max(1, len(chunk["content"])),
                ))

            doc.chunk_count = len(chunks)
            doc.status = "ready"
            db.commit()
    except Exception as e:
        doc.status = "failed"
        doc.error = str(e)
        db.commit()
    finally:
        db.close()
