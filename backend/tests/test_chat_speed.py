"""对话提速（2026-09-06）：查询改写默认关闭、思考模式透传、default_params 校验、检索并行合并。

不发真实模型请求：改写与检索都用 monkeypatch 的假实现。
"""
from types import SimpleNamespace

import pytest

from app.config import settings
from app.model_gateway.gateway import build_llm, reset_llm_cache
from app.services import chat_service

STUB = SimpleNamespace(id=999003, name="pytest-speed")


def _model(default_params: dict, model_id: int = 999, updated_at: str = "2026-09-06T00:00:00"):
    from app.core.security import encrypt_secret
    return SimpleNamespace(id=model_id, updated_at=updated_at, model_name="x", api_key_enc=encrypt_secret("sk-test"), api_base="http://upstream.test/v1/", default_params=default_params)


def test_build_llm_reuses_instance_until_model_config_changes():
    reset_llm_cache()
    first = build_llm(_model({"temperature": 0.7}))
    assert build_llm(_model({"temperature": 0.7})) is first  # 同一 id + updated_at 复用（连接池共享）
    changed = build_llm(_model({"thinking": "disabled"}, updated_at="2026-09-06T00:00:01"))
    assert changed is not first and changed.extra_body == {"thinking": {"type": "disabled"}}
    assert build_llm(_model({"temperature": 0.7}, model_id=1000)) is not changed  # 不同模型各自实例
    reset_llm_cache()


def test_rewrite_disabled_by_default_uses_original_query(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUERY_REWRITE_ENABLED", False)
    monkeypatch.setattr(chat_service, "_rewrite_queries", lambda *a, **k: pytest.fail("默认关闭时不应调用改写"))
    assert chat_service._queries_for(STUB, object(), "原问题") == ["原问题"]


def test_rewrite_enabled_calls_model_rewriter(monkeypatch):
    monkeypatch.setattr(settings, "RAG_QUERY_REWRITE_ENABLED", True)
    monkeypatch.setattr(chat_service, "_rewrite_queries", lambda model, llm, text: [text, text + "（同义）"])
    assert chat_service._queries_for(STUB, object(), "原问题") == ["原问题", "原问题（同义）"]


def test_build_llm_passes_thinking_only_when_set():
    reset_llm_cache()
    assert getattr(build_llm(_model({"temperature": 0.7}, updated_at="t0")), "extra_body", None) in (None, {})
    assert build_llm(_model({"thinking": "disabled"}, updated_at="t1")).extra_body == {"thinking": {"type": "disabled"}}
    assert build_llm(_model({"thinking": "enabled"}, updated_at="t2")).extra_body == {"thinking": {"type": "enabled"}}
    # 非法值不透传（入口已 422，这里兜底）
    assert getattr(build_llm(_model({"thinking": "maybe"}, updated_at="t3")), "extra_body", None) in (None, {})
    reset_llm_cache()


def test_model_api_rejects_invalid_thinking(client, auth_headers):
    body = {"name": "pytest-speed-model", "provider": "openai", "api_base": "http://upstream.test/v1", "api_key": "sk-test", "model_name": "x", "default_params": {"thinking": "maybe"}}
    r = client.post("/api/v1/models", headers=auth_headers, json=body)
    assert r.status_code == 422, r.text
    assert "thinking" in r.json()["detail"][0]["msg"]
    body["default_params"] = {"thinking": "disabled", "temperature": 0.3}
    r = client.post("/api/v1/models", headers=auth_headers, json=body)
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    try:
        assert r.json()["default_params"] == {"thinking": "disabled", "temperature": 0.3}
    finally:
        client.delete(f"/api/v1/models/{mid}", headers=auth_headers)


def test_retrieve_all_runs_every_pair_and_merges_by_best_score(monkeypatch):
    calls: list = []

    def _fake(kb_id, query, top_k, role=None):
        calls.append((kb_id, query))
        score = 0.9 if query == "q1" else 0.5
        return {"items": [{"chunk_id": 1, "doc_name": "d", "content": "c", "score": score}, {"chunk_id": 10 + kb_id, "doc_name": "d", "content": "c2", "score": 0.3}], "stats": {"acl_rejected": 1}}

    monkeypatch.setattr(chat_service, "retrieve_with_stats", _fake)
    monkeypatch.setattr(settings, "RAG_TOP_K", 4)
    citations, rejected, mode = chat_service._retrieve_all([1, 2], ["q1", "q2"], role="admin")
    assert sorted(calls) == [(1, "q1"), (1, "q2"), (2, "q1"), (2, "q2")]  # 每个 (知识库, 查询) 各检索一次
    assert rejected == 4 and mode is None
    # 同一 (kb, chunk) 只保留最高分；按分数降序
    by_key = {(c["kb_id"], c["chunk_id"]): c["score"] for c in citations}
    assert by_key[(1, 1)] == 0.9 and by_key[(2, 1)] == 0.9
    assert [c["score"] for c in citations] == sorted([c["score"] for c in citations], reverse=True)
    assert len(citations) == 4
