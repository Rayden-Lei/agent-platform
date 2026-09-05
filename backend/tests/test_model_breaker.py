"""模型调用熔断（`12-差距补齐开发计划.md` 1.4，FR-027）：状态机单元测试 + 经工作流智能体节点 / 连通测试的集成测试。

上游模型一律 mock（monkeypatch gateway.ChatOpenAI），不发网络请求。
"""
import threading
from types import SimpleNamespace

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage

from app.config import settings
from app.core.exceptions import BizError
from app.core.security import encrypt_secret
from app.db.models import ModelConfig
from app.model_gateway import breaker, gateway
from app.services import chat_service

MID, NAME = 999001, "pytest-breaker"
STUB = SimpleNamespace(id=MID, name=NAME)


def _conn_error() -> Exception:
    return openai.APIConnectionError(request=httpx.Request("POST", "http://upstream.test/v1/chat/completions"))


def _status_error(code: int) -> Exception:
    resp = httpx.Response(code, request=httpx.Request("POST", "http://upstream.test/v1/chat/completions"))
    return openai.APIStatusError(f"http {code}", response=resp, body=None)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """每个用例从干净的熔断表与固定时钟开始；用 clock['now'] 推进时间。"""
    monkeypatch.setattr(settings, "MODEL_BREAKER_FAIL_THRESHOLD", 5)
    monkeypatch.setattr(settings, "MODEL_BREAKER_OPEN_SECONDS", 30)
    state = {"now": 1_800_000_000.0}
    monkeypatch.setattr(breaker, "_clock", lambda: state["now"])
    breaker.reset()
    yield state
    breaker.reset()


def _open(model_id: int = MID, name: str = NAME) -> None:
    for _ in range(settings.MODEL_BREAKER_FAIL_THRESHOLD):
        breaker.record_failure(model_id, name, _conn_error())


# ---------- 状态机 ----------

def test_opens_after_consecutive_failures():
    for _ in range(4):
        assert breaker.record_failure(MID, NAME, _conn_error()) is True
        breaker.before_call(MID, NAME)  # 未到阈值仍放行
    breaker.record_failure(MID, NAME, _conn_error())
    with pytest.raises(BizError) as ei:
        breaker.before_call(MID, NAME)
    assert ei.value.status_code == 503
    assert "熔断中" in ei.value.detail and NAME in ei.value.detail
    assert ei.value.headers["Retry-After"] == "30"


def test_open_state_fails_fast_without_calling_upstream():
    _open()
    calls: list = []

    class _LLM:
        def invoke(self, x):
            calls.append(x)
            return AIMessage(content="ok")

    with pytest.raises(BizError):
        gateway.guarded_invoke(STUB, _LLM(), "hi")
    assert calls == []


def test_half_open_allows_single_probe(clock):
    _open()
    clock["now"] += 30
    breaker.before_call(MID, NAME)  # 到期：放行一个探测
    with pytest.raises(BizError) as ei:
        breaker.before_call(MID, NAME)  # 探测进行中，并发的第二个仍拒绝
    assert ei.value.headers["Retry-After"] == "1"
    assert breaker.status()[0]["state"] == breaker.STATE_HALF_OPEN


def test_half_open_success_closes(clock):
    _open()
    clock["now"] += 30
    breaker.before_call(MID, NAME)
    breaker.record_success(MID, NAME)
    assert breaker.status() == []
    breaker.before_call(MID, NAME)
    breaker.before_call(MID, NAME)  # 关闭后不再限制并发


def test_half_open_failure_reopens(clock):
    _open()
    clock["now"] += 30
    breaker.before_call(MID, NAME)
    breaker.record_failure(MID, NAME, _conn_error())
    with pytest.raises(BizError):
        breaker.before_call(MID, NAME)
    assert breaker.status()[0]["state"] == breaker.STATE_OPEN


def test_success_resets_consecutive_counter():
    for _ in range(4):
        breaker.record_failure(MID, NAME, _conn_error())
    breaker.record_success(MID, NAME)
    for _ in range(4):
        breaker.record_failure(MID, NAME, _conn_error())
    breaker.before_call(MID, NAME)  # 4 + 4 不连续，不熔断


@pytest.mark.parametrize("exc,counted", [
    (_conn_error(), True),
    (openai.APITimeoutError(request=httpx.Request("POST", "http://upstream.test")), True),
    (TimeoutError("local timeout"), True),
    (_status_error(429), True),
    (_status_error(500), True),
    (_status_error(502), True),
    (_status_error(401), False),
    (_status_error(400), False),
    (_status_error(404), False),
    (ValueError("程序错误"), False),
])
def test_failure_classification(exc, counted):
    assert breaker.counts_as_failure(exc) is counted
    assert breaker.record_failure(MID, NAME, exc) is counted


def test_auth_errors_never_open():
    for _ in range(10):
        breaker.record_failure(MID, NAME, _status_error(401))
    breaker.before_call(MID, NAME)
    assert breaker.status() == []


def test_half_open_probe_hitting_auth_error_closes(clock):
    """探测拿到 401：上游可达只是配置错，按恢复处理。"""
    _open()
    clock["now"] += 30
    breaker.before_call(MID, NAME)
    assert breaker.record_failure(MID, NAME, _status_error(401)) is False
    assert breaker.status() == []


def test_threshold_zero_never_opens(monkeypatch):
    monkeypatch.setattr(settings, "MODEL_BREAKER_FAIL_THRESHOLD", 0)
    for _ in range(10):
        assert breaker.record_failure(MID, NAME, _conn_error()) is False
    breaker.before_call(MID, NAME)
    assert breaker.status() == []


def test_build_llm_disables_sdk_retries():
    assert settings.MODEL_MAX_RETRIES == 0
    model = ModelConfig(id=1, name="m", provider="openai", api_base="http://upstream.test/v1", api_key_enc=encrypt_secret("sk-test"), model_name="x", default_params={})
    llm = gateway.build_llm(model)
    assert llm.max_retries == 0


# ---------- 摘要与查询改写走降级并计数 ----------

def test_summary_degrades_when_breaker_open():
    _open()
    calls: list = []

    class _LLM:
        def invoke(self, x):
            calls.append(x)
            return AIMessage(content="不该被调用")

    pending = [AIMessage(content="早先的回答 " * 20)]
    assert chat_service._summarize_history(STUB, _LLM(), "", pending) is None  # 返回 None 由调用方退回截断原文
    assert calls == []


def test_rewrite_timeout_counts_toward_breaker(monkeypatch):
    monkeypatch.setattr(chat_service, "REWRITE_TIMEOUT_SECONDS", 0.05)
    release = threading.Event()

    class _SlowLLM:
        def invoke(self, x):
            release.wait(10)
            return AIMessage(content="慢")

    try:
        for _ in range(5):
            assert chat_service._rewrite_queries(STUB, _SlowLLM(), "问题") == ["问题"]
        with pytest.raises(BizError):
            breaker.before_call(MID, NAME)
    finally:
        release.set()  # 放掉后台线程，避免它们在解释器退出时被 join 卡住


# ---------- 集成：工作流智能体节点、连通测试、系统状态 ----------

class _FailingChatOpenAI:
    """替身：构造签名与 ChatOpenAI 兼容，调用一律连接失败并计数。"""

    calls = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke(self, *_a, **_k):
        type(self).calls += 1
        raise _conn_error()

    async def ainvoke(self, *_a, **_k):
        type(self).calls += 1
        raise _conn_error()


class _HealthyChatOpenAI(_FailingChatOpenAI):
    def invoke(self, *_a, **_k):
        type(self).calls += 1
        return AIMessage(content="pong")

    async def ainvoke(self, *_a, **_k):
        type(self).calls += 1
        return AIMessage(content="pong")


def _create_model(client, auth_headers, name: str) -> int:
    r = client.post("/api/v1/models", headers=auth_headers, json={
        "name": name, "provider": "openai", "api_base": "http://upstream.test/v1", "api_key": "sk-test", "model_name": "x", "default_params": {},
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_agent_node_fails_fast_after_threshold(client, auth_headers, monkeypatch):
    monkeypatch.setattr(gateway, "ChatOpenAI", _FailingChatOpenAI)
    _FailingChatOpenAI.calls = 0
    mid = _create_model(client, auth_headers, "pytest-breaker-model")
    agent = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-breaker-agent", "description": "", "system_prompt": "你是助手", "model_id": mid}).json()
    graph = {
        "nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "a", "type": "agent", "config": {"agent_id": agent["id"]}}, {"id": "e", "type": "end", "config": {}}],
        "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "e"}],
    }
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-breaker-wf", "description": "", "graph": graph}).json()
    try:
        for i in range(5):
            r = client.post(f"/api/v1/workflows/{wf['id']}/run", headers=auth_headers, json={"input": "hi"})
            assert r.status_code == 200 and r.json()["status"] == "failed", r.text
            assert "熔断中" not in r.json()["error"]
        assert _FailingChatOpenAI.calls == 5

        r = client.post(f"/api/v1/workflows/{wf['id']}/run", headers=auth_headers, json={"input": "hi"})
        assert r.json()["status"] == "failed"
        assert "熔断中" in r.json()["error"]
        assert _FailingChatOpenAI.calls == 5  # 第 6 次没有打到上游

        body = client.get("/api/v1/system/status", headers=auth_headers).json()
        entry = next(b for b in body["model_breakers"] if b["model_id"] == mid)
        assert entry["state"] == "open" and entry["consecutive_failures"] == 5 and entry["retry_after_seconds"] == 30
        assert any(d["item"] == "model_breaker" and "pytest-breaker-model" in d["message"] for d in body["degraded"])
    finally:
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{mid}", headers=auth_headers)


def test_connectivity_test_closes_open_breaker(client, auth_headers, monkeypatch):
    mid = _create_model(client, auth_headers, "pytest-breaker-recover")
    try:
        _open(mid, "pytest-breaker-recover")
        assert breaker.status()[0]["state"] == "open"
        monkeypatch.setattr(gateway, "ChatOpenAI", _HealthyChatOpenAI)
        r = client.post(f"/api/v1/models/{mid}/test", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["ok"] is True
        assert breaker.status() == []
    finally:
        client.delete(f"/api/v1/models/{mid}", headers=auth_headers)


def test_status_without_breakers_has_empty_list(client, auth_headers):
    body = client.get("/api/v1/system/status", headers=auth_headers).json()
    assert body["model_breakers"] == []
    assert "model_breaker" not in [d["item"] for d in body["degraded"]]
