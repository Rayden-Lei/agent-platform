"""Rerank 模型接入（FR-032，`12` 第 3.1 步）：两种协议、超时降级、未配置、空候选、鉴权顺序。

重排服务用 httpx.MockTransport 替身，不发网络请求。
"""
import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.db.session import SessionLocal
from app.rag import rerank as rr
from app.rag import retriever
from app.services import system_service

_REAL_CLIENT = httpx.Client  # 在任何 monkeypatch 之前记住真实类，避免同一用例内二次打桩把假工厂当成真类


def _degraded() -> list:
    db = SessionLocal()
    try:
        return system_service.get_system_status(db)["degraded"]
    finally:
        db.close()


def _candidates():
    return [
        {"content": "工作流由 LangGraph 执行", "score": 0.9, "chunk": SimpleNamespace(meta={"is_public": True})},
        {"content": "文档上传到 MinIO 后异步解析切片向量化", "score": 0.5, "chunk": SimpleNamespace(meta={"is_public": True})},
        {"content": "知识库权限按角色可见", "score": 0.4, "chunk": SimpleNamespace(meta={"is_public": False, "visible_roles": ["admin"]})},
    ]


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "cohere")
    monkeypatch.setattr(settings, "RERANK_API_BASE", "http://rerank.test/v1")
    monkeypatch.setattr(settings, "RERANK_API_KEY", "rk-test")
    monkeypatch.setattr(settings, "RERANK_MODEL", "test-reranker")
    monkeypatch.setattr(settings, "RERANK_TIMEOUT", 1)
    monkeypatch.setattr(rr, "_last_failure", None)
    yield
    monkeypatch.setattr(rr, "_last_failure", None)


def _mock_client(monkeypatch, handler):
    """把 rerank 模块里的 httpx.Client 换成走 MockTransport 的版本，并记录请求。"""
    seen: list = []

    def _handler(request: httpx.Request):
        seen.append(request)
        return handler(request)

    def _factory(**kwargs):
        kwargs.pop("trust_env", None)
        return _REAL_CLIENT(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(rr.httpx, "Client", _factory)
    return seen


def test_cohere_protocol_orders_by_relevance_and_marks_mode(configured, monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/rerank" and body["model"] == "test-reranker" and len(body["documents"]) == 3
        assert request.headers["authorization"] == "Bearer rk-test"
        return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.98}, {"index": 0, "relevance_score": 0.2}, {"index": 2, "relevance_score": 0.01}]})

    seen = _mock_client(monkeypatch, handler)
    ranked = rr.rerank("文档上传后怎么处理", _candidates())
    assert len(seen) == 1
    assert [c["content"][:4] for c in ranked] == ["文档上传", "工作流由", "知识库权"]
    assert ranked[0]["rerank_mode"] == "model" and ranked[0]["rerank_score"] == 0.98 and ranked[0]["score"] == 0.98
    assert rr.rerank_status()["mode"] == "model" and rr.rerank_status()["last_error"] is None


def test_dashscope_protocol_parses_output_results(configured, monkeypatch):
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "dashscope")

    def handler(request):
        body = json.loads(request.content)
        assert request.url.path.endswith("/services/rerank/text-rerank/text-rerank")
        assert body["input"]["query"] == "q" and len(body["input"]["documents"]) == 3 and body["parameters"]["return_documents"] is False
        return httpx.Response(200, json={"output": {"results": [{"index": 2, "relevance_score": 0.7}, {"index": 0, "relevance_score": 0.1}]}})

    _mock_client(monkeypatch, handler)
    ranked = rr.rerank("q", _candidates())
    assert [round(c["score"], 2) for c in ranked] == [0.7, 0.1, 0.0]  # 服务没返回的条目按 0 分
    assert ranked[0]["content"].startswith("知识库")


def test_timeout_falls_back_to_lexical_and_reports_degraded(configured, monkeypatch, caplog):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    _mock_client(monkeypatch, handler)
    with caplog.at_level("WARNING", logger="app.rag.rerank"):
        ranked = rr.rerank("知识库 权限", _candidates())
    assert ranked and all(c["rerank_mode"] == "lexical" and c["rerank_score"] is None for c in ranked)
    assert any("退回词法重排" in r.getMessage() for r in caplog.records)
    status = rr.rerank_status()
    assert status["mode"] == "lexical" and status["configured"] is True and status["last_error"]["error"]
    degraded = _degraded()
    assert any(d["item"] == "rerank" for d in degraded)
    # 服务恢复后清掉故障
    _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]}))
    rr.rerank("q", _candidates()[:1])
    assert rr.rerank_status()["mode"] == "model"


def test_unconfigured_is_lexical_and_not_degraded(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "")
    monkeypatch.setattr(rr, "_last_failure", None)
    seen = _mock_client(monkeypatch, lambda request: pytest.fail("未配置时不应调用重排服务"))
    ranked = rr.rerank("知识库 权限", _candidates())
    assert seen == [] and ranked[0]["rerank_mode"] == "lexical"
    status = rr.rerank_status()
    assert status["configured"] is False and status["mode"] == "lexical"
    assert not any(d["item"] == "rerank" for d in _degraded())


def test_empty_candidates_do_not_call_service(configured, monkeypatch):
    seen = _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"results": []}))
    assert rr.rerank("q", []) == []
    assert seen == []


def test_authorization_still_applies_after_model_rerank(configured, monkeypatch):
    """模型把受限切片排到第一也不能越权：鉴权在重排之后逐条执行，且模型分阈值按 RERANK_* 取。"""
    _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"results": [{"index": 2, "relevance_score": 0.99}, {"index": 1, "relevance_score": 0.3}, {"index": 0, "relevance_score": 0.001}]}))
    monkeypatch.setattr(settings, "RERANK_MIN_SCORE", 0.05)
    monkeypatch.setattr(settings, "RERANK_GAP_RATIO", 0.02)
    kept, rejected = retriever._rank_and_authorize("q", _candidates(), role="developer")
    assert rejected == 1  # 受限切片被鉴权剔除
    assert [c["content"][:4] for c in kept] == ["文档上传"]  # 0.001 低于模型阈值被淘汰
    assert kept[0]["rerank_mode"] == "model"
