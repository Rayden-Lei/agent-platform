from sqlalchemy import select

from app.config import settings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.rag.embeddings import embed_query


def retrieve(kb_id: int, query: str, top_k: int = None) -> list:
    top_k = top_k or settings.RAG_TOP_K
    vec = embed_query(query)
    db = SessionLocal()
    try:
        dist = DocumentChunk.embedding.cosine_distance(vec)
        stmt = (
            select(DocumentChunk, dist)
            .where(DocumentChunk.kb_id == kb_id)
            .order_by(dist)
            .limit(top_k)
        )
        rows = db.execute(stmt).all()
        results = []
        for chunk, distance in rows:
            doc = db.get(Document, chunk.doc_id)
            results.append({
                "content": chunk.content,
                "score": round(1 - float(distance), 4),
                "doc_id": chunk.doc_id,
                "doc_name": doc.name if doc else "",
                "meta": chunk.meta or {},
            })
        return results
    finally:
        db.close()
