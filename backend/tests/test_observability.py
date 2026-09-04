"""可观测性：追踪 ID 贯穿响应头与错误体，未处理异常不再裸奔。"""
import pytest
from fastapi.testclient import TestClient

from app.core.request_context import REQUEST_ID_HEADER, sanitize_request_id
from app.main import app


def test_response_carries_trace_header(client):
    r = client.get("/health")
    assert r.headers.get(REQUEST_ID_HEADER)


def test_incoming_trace_id_is_reused(client):
    r = client.get("/health", headers={"X-Request-Id": "caller-trace-001"})
    assert r.headers[REQUEST_ID_HEADER] == "caller-trace-001"


def test_malformed_trace_id_is_replaced(client):
    r = client.get("/health", headers={"X-Request-Id": "bad id with spaces"})
    assert r.headers[REQUEST_ID_HEADER] != "bad id with spaces"
    assert " " not in r.headers[REQUEST_ID_HEADER]


@pytest.mark.parametrize("value,expected", [
    ("abc-123", "abc-123"),
    ("A" * 64, "A" * 64),
    ("A" * 65, None),          # 超长：截断不如拒绝，避免日志被撑爆
    ("bad id", None),          # 空格：会破坏日志分词
    ("x\ny", None),            # 换行：响应头注入
    ("", None),
    (None, None),
])
def test_sanitize_request_id(value, expected):
    assert sanitize_request_id(value) == expected


def test_business_error_body_has_trace_id(client, auth_headers):
    r = client.get("/api/v1/workflows/99999999", headers=auth_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "工作流不存在"
    assert r.json()["trace_id"] == r.headers[REQUEST_ID_HEADER]


def test_unauthenticated_error_body_has_trace_id(client):
    r = client.get("/api/v1/models")
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "未认证"
    assert r.json()["trace_id"] == r.headers[REQUEST_ID_HEADER]


def test_unhandled_exception_returns_500_without_leaking_internals(auth_headers, monkeypatch):
    """未处理异常：500 + 可读提示 + 追踪 ID，且不把异常类型和堆栈吐给调用方。"""
    from app.api.v1 import system as system_api

    def boom(*_args, **_kwargs):
        raise RuntimeError("测试用未处理异常")

    monkeypatch.setattr(system_api.system_service, "get_system_status", boom)
    # 默认的 TestClient 会把服务端异常直接抛出来，这里要的是真实的 500 响应
    raw = TestClient(app, raise_server_exceptions=False)
    r = raw.get("/api/v1/system/status", headers=auth_headers)

    assert r.status_code == 500
    body = r.json()
    assert body["trace_id"] == r.headers[REQUEST_ID_HEADER]
    assert "RuntimeError" not in body["detail"]
    assert "测试用未处理异常" not in body["detail"]
