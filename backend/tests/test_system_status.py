"""降级可见：向量后端模式、登录限流状态、切片 meta 里的向量后端快照。"""
from app.config import settings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.rag import embeddings, pipeline


def test_health_reports_embedding_mode(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["embedding_mode"] in ("model", "hash")


def test_system_status_reports_all_dependencies(client, auth_headers):
    r = client.get("/api/v1/system/status", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["database"]["ok"] is True
    assert set(body["embedding"]) == {"mode", "model", "dim", "configured", "reason", "last_error"}
    assert body["embedding"]["mode"] in ("model", "hash")
    assert isinstance(body["login_guard"]["enabled"], bool)
    assert isinstance(body["scheduler"]["registered_jobs"], int)
    assert isinstance(body["degraded"], list)


def test_hash_fallback_shows_up_as_degraded(client, auth_headers):
    """当前环境用 hash 兜底时，degraded 必须点名 embedding，否则降级就是不可见的。"""
    body = client.get("/api/v1/system/status", headers=auth_headers).json()
    items = [d["item"] for d in body["degraded"]]
    if body["embedding"]["mode"] == "hash":
        assert "embedding" in items
        assert body["embedding"]["reason"]
    else:
        assert "embedding" not in items


def test_caller_cannot_read_system_status(client, auth_headers):
    u = client.post("/api/v1/users", headers=auth_headers, json={
        "username": "pytest-status-caller", "password": "pytest-Passw0rd", "role": "caller",
    })
    assert u.status_code == 200, u.text
    try:
        token = client.post("/api/v1/auth/login", json={
            "username": "pytest-status-caller", "password": "pytest-Passw0rd",
        }).json()["token"]
        r = client.get("/api/v1/system/status", headers={"Authorization": "Bearer " + token})
        assert r.status_code == 403, r.text
    finally:
        client.delete(f"/api/v1/users/{u.json()['id']}", headers=auth_headers)


def test_embedding_failure_degrades_and_is_recorded(monkeypatch):
    """配了向量模型但调用失败：降级 hash，并在状态里留下失败原因。"""
    class _Broken:
        def embed_documents(self, texts):
            raise RuntimeError("模拟向量服务不可用")

        def embed_query(self, text):
            raise RuntimeError("模拟向量服务不可用")

    monkeypatch.setattr(embeddings.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(embeddings, "get_embeddings", lambda: _Broken())
    monkeypatch.setattr(embeddings, "_last_failure", None)

    result = embeddings.embed_texts_detailed(["向量服务挂了也要能入库"])
    assert result.mode == "hash"
    assert len(result.vectors) == 1
    assert len(result.vectors[0]) == settings.EMBEDDING_DIM

    status = embeddings.embedding_status()
    assert status["mode"] == "hash"
    assert status["configured"] is True
    assert "模拟向量服务不可用" in status["last_error"]["error"]


def test_embedding_status_without_key_is_configuration_degradation(monkeypatch):
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_API_KEY", "")
    monkeypatch.setattr(embeddings, "_last_failure", None)
    status = embeddings.embedding_status()
    assert status["configured"] is False
    assert status["mode"] == "hash"
    assert status["last_error"] is None


def _make_kb(client, auth_headers, name: str) -> dict:
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": name, "description": "pytest", "embedding_model": "pytest", "chunk_size": 200, "chunk_overlap": 20,
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_chunk_meta_records_embedding_backend(client, auth_headers, monkeypatch):
    """切片 meta 要记下实际使用的向量后端，换模型或降级后才知道哪些切片需要重建。"""
    kb = _make_kb(client, auth_headers, "pytest-kb-embedding-meta")
    db = SessionLocal()
    try:
        doc = Document(kb_id=kb["id"], name="pytest-meta.txt", file_path="pytest/unused.txt", file_type="txt", status="uploading")
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # 不接 MinIO：只验证向量后端信息有没有写进 meta
        monkeypatch.setattr(pipeline, "download_file", lambda *a, **k: None)
        monkeypatch.setattr(pipeline, "parse_document", lambda *a, **k: [
            {"content": "智枢平台会把向量后端写进切片 meta。", "meta": {"type": "text"}},
        ])
        pipeline.process_document(doc.id)

        db.expire_all()
        assert db.get(Document, doc.id).status == "ready", db.get(Document, doc.id).error
        chunk = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc.id).first()
        assert chunk is not None
        assert chunk.meta["embedding_mode"] in ("model", "hash")
        assert chunk.meta["embedding_model"]
        assert chunk.meta["embedding_dim"] == settings.EMBEDDING_DIM
    finally:
        db.close()
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)


def test_document_processing_failure_is_recorded(client, auth_headers, monkeypatch):
    """解析失败要落到 doc.error，而不是让后台任务静默炸掉、文档永远停在 parsing。"""
    kb = _make_kb(client, auth_headers, "pytest-kb-parse-failure")
    db = SessionLocal()
    try:
        doc = Document(kb_id=kb["id"], name="pytest-bad.txt", file_path="pytest/unused.txt", file_type="txt", status="uploading")
        db.add(doc)
        db.commit()
        db.refresh(doc)

        monkeypatch.setattr(pipeline, "download_file", lambda *a, **k: None)

        def _explode(*_a, **_k):
            raise RuntimeError("模拟解析失败")

        monkeypatch.setattr(pipeline, "parse_document", _explode)
        pipeline.process_document(doc.id)

        db.expire_all()
        failed = db.get(Document, doc.id)
        assert failed.status == "failed"
        assert "模拟解析失败" in failed.error
    finally:
        db.close()
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)


def test_process_document_on_missing_doc_is_noop():
    pipeline.process_document(99999999)  # 不存在的文档不应抛异常
