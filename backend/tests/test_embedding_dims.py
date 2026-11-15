"""不同维度的向量模型共存（2026-11-15 切片向量按维度分列）。

改造前 `document_chunks.embedding` 是定长的 `vector(1024)`，一个实例只能有一个维度，
2026-11-08 那次改造只能在保存模型时拦住维度不一致的模型（422）—— 绕开问题而不是解决问题。
现在每个支持维度各占一列，入库与检索按知识库绑定的模型选列。

本文件盯三件事（都是"改之前会失败"的）：
1. **两个不同维度的库共存、各自入库、各自检索、互不串** —— 本任务的核心断言；
2. 维度不在支持集合内的模型仍然被拒（422），不会溜到入库时才炸；
3. 库的模型被删/停用/维度不受支持时，检索**不出结果且不返回垃圾**，不会退回全局配置用错向量空间。
"""
import uuid

import pytest

from app.config import settings
from app.db.models import Document, DocumentChunk, EmbeddingModel, KnowledgeBase
from app.db.session import SessionLocal
from app.rag import embedding_dims, pipeline, retriever
from app.rag.embeddings import EmbeddingResult


def _uid() -> str:
    return uuid.uuid4().hex[:6]


def _make_model(client, auth_headers, *, dim: int, name: str | None = None) -> dict:
    r = client.post("/api/v1/embedding-models", headers=auth_headers, json={
        "name": name or f"pytest-dim-model-{_uid()}", "provider": "openai",
        "api_base": "https://pytest.invalid/v1", "api_key": "pytest-key",
        "model_name": "pytest-embed-model", "dim": dim, "request_size": 20, "is_enabled": True,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _make_kb(client, auth_headers, model_id: int, name: str | None = None) -> dict:
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": name or f"pytest-dim-kb-{_uid()}", "description": "pytest",
        "embedding_model_id": model_id, "chunk_size": 200, "chunk_overlap": 20,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _ensure_model(client, auth_headers, model: dict) -> dict:
    """确认向量模型行还在，不在就按同样参数重建。

    开发库是共享的，别的 pytest 会话的 tests/cleanup.py 会按 `pytest-` 前缀 + 时间窗
    整表回收 —— 同一台机器上并行跑测试时，本用例建好的 `pytest-` 模型可能在某一步之间
    被别人删掉，建库就会撞外键。这是测试环境的并发问题，不是产品缺陷；
    但用例必须在共享库上稳定，所以引用前重新确认一次（重建后 id 会变，返回新的行）。
    """
    got = client.get(f"/api/v1/embedding-models/{model['id']}", headers=auth_headers)
    if got.status_code == 200:
        return model
    r = client.post("/api/v1/embedding-models", headers=auth_headers, json={
        "name": model["name"], "provider": model["provider"], "api_base": model["api_base"],
        "api_key": "pytest-key", "model_name": model["model_name"], "dim": model["dim"],
        "request_size": model["request_size"], "is_enabled": True,
    })
    # 名字可能仍被残留行占着（删除是异步不会，但同前缀冲突会 400）：换个名字重试一次
    if r.status_code == 400:
        r = client.post("/api/v1/embedding-models", headers=auth_headers, json={
            "name": f"pytest-dim-model-{_uid()}", "provider": model["provider"], "api_base": model["api_base"],
            "api_key": "pytest-key", "model_name": model["model_name"], "dim": model["dim"],
            "request_size": model["request_size"], "is_enabled": True,
        })
    assert r.status_code == 200, r.text
    return r.json()


def _insert_chunk(kb_id: int, content: str, *, dim: int, vector: list | None = None) -> int:
    """直接插一条切片（不走 MinIO 与解析），向量写进与 dim 对应的那一列。返回切片 id。"""
    db = SessionLocal()
    try:
        doc = Document(kb_id=kb_id, name=f"pytest-dim-doc-{_uid()}.txt", file_path="pytest/unused.txt",
                       file_type="txt", status="ready")
        db.add(doc)
        db.commit()
        vec = vector if vector is not None else [0.1] * dim
        chunk = DocumentChunk(doc_id=doc.id, kb_id=kb_id, content=content,
                              **{embedding_dims.column_name(dim): vec}, meta={}, token_count=len(content))
        db.add(chunk)
        db.commit()
        return chunk.id
    finally:
        db.close()


# ===== 维度单一来源 =====

def test_supported_dims_endpoint_matches_backend_source(client, auth_headers):
    """支持维度只在后端定义一处，下发给前端做下拉；前端不自己硬编码。"""
    r = client.get("/api/v1/embedding-models/dims", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dims"] == list(embedding_dims.SUPPORTED_DIMS)
    # 3072 超过 pgvector 0.6 的索引上限，必须如实标注"不可索引"，否则"检索变慢"无从排查
    assert 3072 not in body["indexed_dims"]
    assert set(body["indexed_dims"]) == {d for d in embedding_dims.SUPPORTED_DIMS if d <= embedding_dims.INDEX_MAX_DIM}
    assert body["default_dim"] in embedding_dims.SUPPORTED_DIMS


def test_unsupported_dim_is_rejected(client, auth_headers):
    """不在支持集合里的维度必须 422：切片表没有那一列，存进去要到入库时才炸（后台线程，用户只看得到 failed）。"""
    r = client.post("/api/v1/embedding-models", headers=auth_headers, json={
        "name": f"pytest-dim-bad-{_uid()}", "provider": "openai", "api_base": "https://pytest.invalid/v1",
        "api_key": "pytest-key", "model_name": "pytest-embed-model", "dim": 999, "request_size": 20, "is_enabled": True,
    })
    assert r.status_code == 422, r.text
    # 报错要说清可选的维度，不能只说"不行"
    for dim in embedding_dims.SUPPORTED_DIMS:
        assert str(dim) in r.json()["detail"]


@pytest.mark.parametrize("dim", [768, 1536])
def test_each_supported_dim_is_accepted(client, auth_headers, dim):
    """768 / 1536 这两个非当前默认维度必须能存进模型表（改造前一律 422）。"""
    m = _make_model(client, auth_headers, dim=dim)
    try:
        assert m["dim"] == dim
    finally:
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_options_report_index_capability(client, auth_headers):
    """建库下拉要带"这个维度能不能建索引"：3072 维检索走顺序扫描，前端要能提示。"""
    m3072 = _make_model(client, auth_headers, dim=3072)
    try:
        r = client.get("/api/v1/embedding-models/options", headers=auth_headers)
        assert r.status_code == 200, r.text
        opt = next(x for x in r.json()["items"] if x["id"] == m3072["id"])
        assert opt["dim"] == 3072 and opt["indexed"] is False
    finally:
        client.delete(f"/api/v1/embedding-models/{m3072['id']}", headers=auth_headers)


# ===== 核心断言：两个不同维度的库共存、各自入库、各自检索、互不串 =====

def test_two_dimensions_coexist_and_do_not_cross(client, auth_headers, monkeypatch):
    """768 维库与 1536 维库同时存在：各自入库写各自列，检索只命中自己库的切片。

    这条是任务的核心断言。改造前这个用例根本建不出来 —— 第二个库的模型会被 422 拒绝。
    """
    m768 = _make_model(client, auth_headers, dim=768)
    m1536 = _make_model(client, auth_headers, dim=1536)
    m768 = _ensure_model(client, auth_headers, m768)
    m1536 = _ensure_model(client, auth_headers, m1536)
    kb768 = _make_kb(client, auth_headers, m768["id"])
    kb1536 = _make_kb(client, auth_headers, m1536["id"])
    try:
        # 入库：同一段文本进两个库，但用各自模型的维度向量化
        seen_dims: list = []

        def _fake_embed(texts, request_size=None, spec=None):
            seen_dims.append(spec.dim)
            return EmbeddingResult([[0.5] * spec.dim for _ in texts], "model", spec.model, spec.dim)

        monkeypatch.setattr(pipeline, "embed_texts_detailed", _fake_embed)
        monkeypatch.setattr(pipeline, "download_file", lambda *a, **k: None)
        contents = {"768": "768 维库特有的布洛芬说明书内容", "1536": "1536 维库特有的对乙酰氨基酚内容"}

        for kb, key in ((kb768, "768"), (kb1536, "1536")):
            monkeypatch.setattr(pipeline, "parse_document", lambda *a, k=key, **kw: [
                {"content": contents[k], "meta": {"type": "text"}},
            ])
            db = SessionLocal()
            try:
                doc = Document(kb_id=kb["id"], name=f"pytest-dim-ingest-{key}.txt", file_path="pytest/unused.txt",
                               file_type="txt", status="uploading")
                db.add(doc)
                db.commit()
                doc_id = doc.id
            finally:
                db.close()
            pipeline.process_document(doc_id)

        assert sorted(seen_dims) == [768, 1536], "两个库必须各自按自己的维度向量化"

        # 入库落到了正确的列：768 库的切片只有 embedding_768 有值，1536 库的只有 embedding_1536 有值
        db = SessionLocal()
        try:
            for kb, dim, other_dim in ((kb768, 768, 1536), (kb1536, 1536, 768)):
                chunk = db.query(DocumentChunk).filter(DocumentChunk.kb_id == kb["id"]).one()
                assert getattr(chunk, embedding_dims.column_name(dim)) is not None
                assert getattr(chunk, embedding_dims.column_name(other_dim)) is None
                assert chunk.meta["embedding_dim"] == dim
        finally:
            db.close()

        # 检索：查询向量按库的维度产出，命中的只能是本库的切片
        monkeypatch.setattr(settings, "RERANK_PROVIDER", "")
        query_dims: list = []

        def _fake_query(text, spec=None):
            query_dims.append(spec.dim)
            return [0.5] * spec.dim

        monkeypatch.setattr(retriever, "embed_query", _fake_query)

        for kb, key in ((kb768, "768"), (kb1536, "1536")):
            r = client.post(f"/api/v1/knowledge-bases/{kb['id']}/search", headers=auth_headers,
                            json={"query": contents[key], "debug": True, "top_k": 10})
            assert r.status_code == 200, r.text
            hits = [i["content"] for i in r.json()["items"]]
            assert contents[key] in hits, f"{key} 维库必须检索到自己入库的内容"
            # 互不串：另一个维度库的内容绝不能出现在这里
            other = "1536" if key == "768" else "768"
            assert all(contents[other] not in h for h in hits), f"{key} 维库串到了 {other} 维库的内容"
            assert r.json()["stats"]["kb_unsearchable"] is None

        assert sorted(query_dims) == [768, 1536], "查询向量必须按各库模型的维度产出"
    finally:
        for kb in (kb768, kb1536):
            client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        for m in (m768, m1536):
            client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


# ===== 维度不匹配时不返回垃圾结果 =====

def test_chunk_without_query_dimension_is_not_returned(client, auth_headers, monkeypatch):
    """库绑定 1024 维，但切片只有 768 列有值：该切片不是这个向量空间的东西，绝不能当候选返回。

    不过滤 NULL 的话，这些行会以 NULL 距离参与排序，用户拿到一堆与查询无关的"命中"。
    """
    m = _make_model(client, auth_headers, dim=1024)
    kb = _make_kb(client, auth_headers, m["id"])
    try:
        _insert_chunk(kb["id"], "这条切片只有 768 维向量", dim=768)  # 维度与库绑定的模型不一致
        monkeypatch.setattr(retriever, "embed_query", lambda text, spec=None: [0.1] * spec.dim)
        monkeypatch.setattr(settings, "RERANK_PROVIDER", "")

        r = client.post(f"/api/v1/knowledge-bases/{kb['id']}/search", headers=auth_headers,
                        json={"query": "这条切片只有 768 维向量", "debug": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["items"] == [], f"维度不匹配的切片不能返回，实际返回了 {body['items']}"
        assert body["stats"]["candidate_count"] == 0
        assert body["stats"]["kb_unsearchable"] is None  # 库本身没问题，只是没有该维度的切片
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_correct_dimension_sibling_still_returned(client, auth_headers, monkeypatch):
    """同一个库里两种维度的切片混着（迁移遗留 / 换模型的中间态）：只命中维度一致的那条。"""
    m = _make_model(client, auth_headers, dim=1024)
    kb = _make_kb(client, auth_headers, m["id"])
    try:
        good = _insert_chunk(kb["id"], "1024 维的正确切片", dim=1024)
        _insert_chunk(kb["id"], "768 维的错位切片", dim=768)
        monkeypatch.setattr(retriever, "embed_query", lambda text, spec=None: [0.1] * spec.dim)
        monkeypatch.setattr(settings, "RERANK_PROVIDER", "")

        r = client.post(f"/api/v1/knowledge-bases/{kb['id']}/search", headers=auth_headers,
                        json={"query": "1024 维的正确切片", "debug": True})
        assert r.status_code == 200, r.text
        ids = [i["chunk_id"] for i in r.json()["items"]]
        assert good in ids
        assert len(ids) == 1, f"只应返回维度一致的那条，实际 {ids}"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


# ===== 降级行为：库的模型不可用时不出结果，绝不退回全局配置 =====

def test_retrieve_returns_nothing_when_kb_model_disabled(client, auth_headers, monkeypatch):
    """库的模型被停用时：该库不出结果，并且不能用全局 .env 配置凑合查（那是用错向量空间）。"""
    m = _make_model(client, auth_headers, dim=1024)
    kb = _make_kb(client, auth_headers, m["id"])
    try:
        _insert_chunk(kb["id"], "模型停用后这条不该被检索到", dim=1024)
        db = SessionLocal()
        try:
            row = db.get(EmbeddingModel, m["id"])
            row.is_enabled = False
            db.commit()
        finally:
            db.close()

        called: list = []
        monkeypatch.setattr(retriever, "embed_query", lambda text, spec=None: called.append(spec) or [0.1] * settings.EMBEDDING_DIM)
        monkeypatch.setattr(settings, "RERANK_PROVIDER", "")

        r = client.post(f"/api/v1/knowledge-bases/{kb['id']}/search", headers=auth_headers,
                        json={"query": "模型停用后这条不该被检索到", "debug": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["items"] == []
        assert body["stats"]["kb_unsearchable"], "要能看出是这个库不可检索，而不是没命中"
        assert "停用" in body["stats"]["kb_unsearchable"]
        # 关键：连查询向量都不该去算 —— 一旦算了就说明它在用某个兜底配置
        assert called == [], "库不可检索时不得调用向量模型（否则就是在用错配置凑合查）"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        # 模型被停用后仍可删除（没有库绑定它了）；先解绑
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_kb_vector_rejects_missing_model_row(client, auth_headers):
    """库指向的向量模型行不存在时，_kb_vector 必须抛 KBUnsearchable，绝不退回全局配置。

    这条只能在单元层验证：`knowledge_bases.embedding_model_id` 是非空外键且 ON DELETE RESTRICT，
    "悬空 ID"在库里造不出来（删除被库绑定的模型接口层先 409、DB 也会拦）。但代码不能假设
    "外键保证了就不会缺" —— 手工改库、恢复旧备份、跨环境导入都可能留下悬空引用，
    而退回全局配置在维度不同时是用错向量空间，维度相同时更糟：安静地返回另一个空间的垃圾结果。
    """
    from types import SimpleNamespace

    from app.rag.retriever import KBUnsearchable

    db = SessionLocal()
    try:
        kb = SimpleNamespace(id=-1, name="pytest-悬空模型", embedding_model_id=99999999)
        with pytest.raises(KBUnsearchable) as exc:
            retriever._kb_vector(db, kb)
        assert "不存在" in str(exc.value)
    finally:
        db.close()


def test_chat_retrieval_isolates_unsearchable_kb(client, auth_headers, monkeypatch):
    """对话链路里一个库不可检索不能拖垮另一个库的结果（_retrieve_all 是按库并发的）。"""
    from app.services import chat_service

    good_model = _make_model(client, auth_headers, dim=1024)
    bad_model = _make_model(client, auth_headers, dim=1536)
    good_kb = _make_kb(client, auth_headers, good_model["id"])
    bad_kb = _make_kb(client, auth_headers, bad_model["id"])
    try:
        _insert_chunk(good_kb["id"], "仍然应该被检索到的内容", dim=1024)
        _insert_chunk(bad_kb["id"], "坏库里的内容", dim=1536)
        db = SessionLocal()
        try:
            db.get(EmbeddingModel, bad_model["id"]).is_enabled = False
            db.commit()
        finally:
            db.close()

        monkeypatch.setattr(retriever, "embed_query", lambda text, spec=None: [0.1] * spec.dim)
        monkeypatch.setattr(settings, "RERANK_PROVIDER", "")
        result = chat_service._retrieve_all([good_kb["id"], bad_kb["id"]], ["仍然应该被检索到的内容"], "admin")
        contents = [c["content"] for c in result.citations]
        assert any("仍然应该被检索到的内容" in c for c in contents), "好库的结果不能因为坏库而丢失"
        assert all("坏库里的内容" not in c for c in contents)
    finally:
        for kb in (good_kb, bad_kb):
            client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{good_model['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{bad_model['id']}", headers=auth_headers)


# ===== 入库侧的维度防线 =====

def test_pipeline_rejects_vector_with_wrong_length(client, auth_headers, monkeypatch):
    """向量服务返回的长度与声明维度不符时，写库前就拒绝（否则错误会埋在 pgvector 的列宽报错里）。"""
    m = _make_model(client, auth_headers, dim=768)
    kb = _make_kb(client, auth_headers, m["id"])
    try:
        monkeypatch.setattr(pipeline, "download_file", lambda *a, **k: None)
        monkeypatch.setattr(pipeline, "parse_document", lambda *a, **k: [{"content": "维度不符的向量", "meta": {}}])
        # 声明的 spec 是 768 维，却返回 1024 维的向量：模型实际产出与配置不一致
        monkeypatch.setattr(pipeline, "embed_texts_detailed", lambda texts, request_size=None, spec=None: EmbeddingResult(
            [[0.1] * 1024 for _ in texts], "model", spec.model, spec.dim))

        db = SessionLocal()
        try:
            doc = Document(kb_id=kb["id"], name="pytest-dim-wrong.txt", file_path="pytest/unused.txt",
                           file_type="txt", status="uploading")
            db.add(doc)
            db.commit()
            doc_id = doc.id
        finally:
            db.close()

        pipeline.process_document(doc_id)
        db = SessionLocal()
        try:
            failed = db.get(Document, doc_id)
            assert failed.status == "failed"
            assert "维度" in (failed.error or "")
            assert db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).count() == 0
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_pipeline_writes_1536_column(client, auth_headers, monkeypatch):
    """1536 维库入库写 embedding_1536 列，其余维度列保持 NULL。"""
    m = _make_model(client, auth_headers, dim=1536)
    kb = _make_kb(client, auth_headers, m["id"])
    try:
        monkeypatch.setattr(pipeline, "download_file", lambda *a, **k: None)
        monkeypatch.setattr(pipeline, "parse_document", lambda *a, **k: [{"content": "1536 维入库", "meta": {}}])
        monkeypatch.setattr(pipeline, "embed_texts_detailed", lambda texts, request_size=None, spec=None: EmbeddingResult(
            [[0.2] * 1536 for _ in texts], "model", spec.model, spec.dim))

        db = SessionLocal()
        try:
            doc = Document(kb_id=kb["id"], name="pytest-dim-1536.txt", file_path="pytest/unused.txt",
                           file_type="txt", status="uploading")
            db.add(doc)
            db.commit()
            doc_id = doc.id
        finally:
            db.close()

        pipeline.process_document(doc_id)
        db = SessionLocal()
        try:
            assert db.get(Document, doc_id).status == "ready"
            chunk = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).one()
            assert chunk.embedding_1536 is not None
            for other in (768, 1024, 3072):
                assert getattr(chunk, embedding_dims.column_name(other)) is None
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)
