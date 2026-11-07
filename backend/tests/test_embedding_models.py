"""向量模型：维度校验、被引用的模型不能停用/删除、知识库按绑定的模型向量化。

背景（2026-11-08）：改造前 knowledge_bases.embedding_model 只是记录，实际向量化固定读全局配置，
默认值还是个不存在的模型名。现在建库绑定真实模型行，入库与检索都按它走。
"""
from app.config import settings
from app.db.models import KnowledgeBase
from app.db.session import SessionLocal
from app.rag import embeddings, pipeline


def _model_body(**over) -> dict:
    body = {
        "name": "pytest-embed-model", "provider": "openai", "api_base": "https://example.invalid/v1",
        "api_key": "pytest-key", "model_name": "pytest-model", "dim": settings.EMBEDDING_DIM,
        "request_size": 20, "is_enabled": True,
    }
    body.update(over)
    return body


def _create(client, auth_headers, **over):
    r = client.post("/api/v1/embedding-models", headers=auth_headers, json=_model_body(**over))
    assert r.status_code == 200, r.text
    return r.json()


def _make_kb(client, auth_headers, model_id: int, name: str = "pytest-kb-emb") -> dict:
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": name, "description": "pytest", "embedding_model_id": model_id,
        "chunk_size": 200, "chunk_overlap": 20,
    })
    assert r.status_code == 200, r.text
    return r.json()


# ===== 维度校验 =====

def test_dim_mismatch_is_rejected(client, auth_headers):
    """维度与切片表列宽不一致必须 422：pgvector 是定长列，存进去会等到入库时才炸。"""
    other = settings.EMBEDDING_DIM + 256
    r = client.post("/api/v1/embedding-models", headers=auth_headers, json=_model_body(dim=other))
    assert r.status_code == 422, r.text
    assert str(settings.EMBEDDING_DIM) in r.json()["detail"]


def test_dim_matching_column_is_accepted(client, auth_headers):
    m = _create(client, auth_headers, name="pytest-embed-dim-ok")
    try:
        assert m["dim"] == settings.EMBEDDING_DIM
        assert m["has_key"] is True          # 密钥只回"有没有"，不回声
        assert "api_key" not in m
        assert "api_key_enc" not in m
    finally:
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_create_without_key_is_rejected(client, auth_headers):
    r = client.post("/api/v1/embedding-models", headers=auth_headers, json=_model_body(api_key=""))
    assert r.status_code == 422, r.text


def test_duplicate_name_is_rejected(client, auth_headers):
    m = _create(client, auth_headers, name="pytest-embed-dup")
    try:
        r = client.post("/api/v1/embedding-models", headers=auth_headers, json=_model_body(name="pytest-embed-dup"))
        assert r.status_code == 400, r.text
    finally:
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


# ===== 被引用的模型不能停用 / 删除 =====

def test_model_bound_to_kb_cannot_be_disabled_or_deleted(client, auth_headers):
    """停用或删除会让绑定的知识库再也无法入库与检索，必须拦住并给可读原因。"""
    m = _create(client, auth_headers, name="pytest-embed-bound")
    kb = _make_kb(client, auth_headers, m["id"], "pytest-kb-bound")
    try:
        off = client.post(f"/api/v1/embedding-models/{m['id']}/toggle", headers=auth_headers)
        assert off.status_code == 400, off.text
        assert "知识库" in off.json()["detail"]

        gone = client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)
        assert gone.status_code == 409, gone.text
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_unbound_model_can_be_disabled_and_deleted(client, auth_headers):
    m = _create(client, auth_headers, name="pytest-embed-free")
    toggled = client.post(f"/api/v1/embedding-models/{m['id']}/toggle", headers=auth_headers)
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["is_enabled"] is False
    assert client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers).status_code == 200


# ===== 建库契约 =====

def test_kb_requires_existing_enabled_model(client, auth_headers):
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": "pytest-kb-bad-model", "embedding_model_id": 99999999, "chunk_size": 200, "chunk_overlap": 20,
    })
    assert r.status_code == 404, r.text

    m = _create(client, auth_headers, name="pytest-embed-off")
    try:
        client.post(f"/api/v1/embedding-models/{m['id']}/toggle", headers=auth_headers)
        r2 = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
            "name": "pytest-kb-off-model", "embedding_model_id": m["id"], "chunk_size": 200, "chunk_overlap": 20,
        })
        assert r2.status_code == 400, r2.text
    finally:
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_kb_rejects_legacy_embedding_model_field(client, auth_headers):
    """一次切换：旧字段 embedding_model 必须 422，不能悄悄忽略（否则前端以为生效了）。"""
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": "pytest-kb-legacy", "embedding_model": "text-embedding-3-small", "chunk_size": 200, "chunk_overlap": 20,
    })
    assert r.status_code == 422, r.text


def test_kb_returns_bound_model_snapshot(client, auth_headers):
    """列表与详情要带出绑定的模型快照，前端不用再查一次。"""
    m = _create(client, auth_headers, name="pytest-embed-snapshot")
    kb = _make_kb(client, auth_headers, m["id"], "pytest-kb-snapshot")
    try:
        got = client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["embedding_model_id"] == m["id"]
        assert body["embedding_model"]["id"] == m["id"]
        assert body["embedding_model"]["model_name"] == "pytest-model"
        assert body["embedding_model"]["dim"] == settings.EMBEDDING_DIM
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


# ===== 按知识库的模型向量化 =====

def test_pipeline_uses_kb_bound_model(client, auth_headers, monkeypatch):
    """入库必须用知识库绑定的模型配置，不能用全局 .env 的。"""
    m = _create(client, auth_headers, name="pytest-embed-pipeline", model_name="bound-model-name")
    kb = _make_kb(client, auth_headers, m["id"], "pytest-kb-pipeline")
    seen: dict = {}

    def _fake_embed(texts, request_size=None, spec=None):
        seen["model"] = spec.model if spec else None
        seen["dim"] = spec.dim if spec else None
        return embeddings.EmbeddingResult([[0.0] * settings.EMBEDDING_DIM for _ in texts], "model",
                                          spec.model if spec else "none", settings.EMBEDDING_DIM)

    try:
        from app.db.models import Document
        db = SessionLocal()
        doc = Document(kb_id=kb["id"], name="pytest-bound.txt", file_path="pytest/unused.txt",
                       file_type="txt", status="uploading")
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = doc.id
        db.close()

        monkeypatch.setattr(pipeline, "download_file", lambda *a, **k: None)
        monkeypatch.setattr(pipeline, "parse_document", lambda *a, **k: [
            {"content": "绑定模型要真的生效才不是摆设。", "meta": {"type": "text"}},
        ])
        monkeypatch.setattr(pipeline, "embed_texts_detailed", _fake_embed)
        pipeline.process_document(doc_id)

        # 用的是库绑定的那个模型名，不是全局 .env 的
        assert seen["model"] == "bound-model-name"
        assert seen["dim"] == settings.EMBEDDING_DIM
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_spec_for_kb_rejects_missing_or_disabled_model(client, auth_headers):
    """库的模型被删/停用时，spec_for_kb 要明确报错而不是悄悄退回全局配置。"""
    from app.core.exceptions import BizError
    from app.services import embedding_model_service

    m = _create(client, auth_headers, name="pytest-embed-spec")
    kb = _make_kb(client, auth_headers, m["id"], "pytest-kb-spec")
    db = SessionLocal()
    try:
        row = db.get(KnowledgeBase, kb["id"])
        spec = embedding_model_service.spec_for_kb(db, row)
        assert spec.model == "pytest-model"
        assert spec.dim == settings.EMBEDDING_DIM

        # 直接改库模拟"模型被停用"（接口层会拦住，这里验证防御路径）
        from app.db.models import EmbeddingModel
        em = db.get(EmbeddingModel, m["id"])
        em.is_enabled = False
        db.commit()
        db.expire_all()
        row = db.get(KnowledgeBase, kb["id"])
        try:
            embedding_model_service.spec_for_kb(db, row)
            assert False, "停用的模型必须报错"
        except BizError as e:
            assert "停用" in str(e)
    finally:
        db.close()
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_options_lists_only_enabled(client, auth_headers):
    m = _create(client, auth_headers, name="pytest-embed-opt")
    off = _create(client, auth_headers, name="pytest-embed-opt-off")
    try:
        client.post(f"/api/v1/embedding-models/{off['id']}/toggle", headers=auth_headers)
        r = client.get("/api/v1/embedding-models/options", headers=auth_headers)
        assert r.status_code == 200, r.text
        ids = [x["id"] for x in r.json()["items"]]
        assert m["id"] in ids
        assert off["id"] not in ids
        # 候选必须带维度，前端要显示"1024 维"
        assert all("dim" in x for x in r.json()["items"])
    finally:
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{off['id']}", headers=auth_headers)


def test_caller_cannot_manage_embedding_models(client, auth_headers):
    u = client.post("/api/v1/users", headers=auth_headers, json={
        "username": "pytest-embed-caller", "password": "pytest-Passw0rd", "role": "caller",
    })
    assert u.status_code == 200, u.text
    try:
        token = client.post("/api/v1/auth/login", json={
            "username": "pytest-embed-caller", "password": "pytest-Passw0rd",
        }).json()["token"]
        h = {"Authorization": "Bearer " + token}
        assert client.get("/api/v1/embedding-models", headers=h).status_code == 403
        assert client.post("/api/v1/embedding-models", headers=h, json=_model_body()).status_code == 403
    finally:
        client.delete(f"/api/v1/users/{u.json()['id']}", headers=auth_headers)
