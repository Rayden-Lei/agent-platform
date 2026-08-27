import os
import tempfile

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.db.models import Document, DocumentChunk, KnowledgeBase
from app.db.session import SessionLocal
from app.rag.embeddings import embed_texts
from app.rag.minio_client import download_file
from app.rag.parser import parse_text


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
            text = parse_text(local_path, doc.file_type)

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=kb.chunk_size or 500,
                chunk_overlap=kb.chunk_overlap or 50,
                separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
            )
            chunks = splitter.split_text(text)
            if not chunks:
                doc.status = "ready"
                doc.chunk_count = 0
                db.commit()
                return

            doc.status = "chunking"
            db.commit()

            embeddings = embed_texts(chunks)

            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                db.add(DocumentChunk(
                    doc_id=doc.id,
                    kb_id=doc.kb_id,
                    content=chunk,
                    embedding=emb,
                    meta={"index": i},
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
