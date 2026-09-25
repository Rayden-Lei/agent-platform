"""模型参数分层生效（docs/15 3.5.1，FR-042）：模型 default_params ← 智能体 params；白名单键与取值范围 422；实例缓存按生效参数区分。

2026-09-25 前智能体的"高级参数"从未生效：表单写着透传，运行时只读模型默认参数，改了没有任何效果也不报错。
不发真实模型请求：ChatOpenAI 换成只记录构造参数的替身。
"""
import uuid
from types import SimpleNamespace

import pytest

from app.core.security import encrypt_secret
from app.db.session import SessionLocal
from app.model_gateway import gateway
from app.model_gateway.gateway import build_llm, reset_llm_cache
from app.services import chat_service


class _RecordingChatOpenAI:
    """记录构造参数；invoke 返回固定回答，供工作流智能体节点跑通。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke(self, messages):
        return SimpleNamespace(content="ok")


def _model(default_params: dict, model_id: int = 990042, updated_at: str = "2026-09-25T00:00:00"):
    return SimpleNamespace(id=model_id, name="pytest-params", updated_at=updated_at, model_name="x",
                           api_key_enc=encrypt_secret("sk-test"), api_base="http://upstream.test/v1", default_params=default_params)


@pytest.fixture
def recording(monkeypatch):
    reset_llm_cache()
    monkeypatch.setattr(gateway, "ChatOpenAI", _RecordingChatOpenAI)
    yield
    reset_llm_cache()


@pytest.fixture
def model_id(client, auth_headers):
    r = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-params-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {"temperature": 0.2, "max_tokens": 512},
    })
    assert r.status_code == 200, r.text
    yield r.json()["id"]
    client.delete(f"/api/v1/models/{r.json()['id']}", headers=auth_headers)


def _agent_body(model_id: int, params: dict) -> dict:
    return {"name": "pytest-params-agent-" + uuid.uuid4().hex[:6], "description": "", "system_prompt": "你是助手", "model_id": model_id, "params": params}


def test_agent_params_override_model_defaults_and_empty_values_do_not(recording):
    m = _model({"temperature": 0.2, "max_tokens": 512})
    assert build_llm(m).kwargs["temperature"] == 0.2
    llm = build_llm(m, {"temperature": 0.9, "top_p": None})
    assert llm.kwargs["temperature"] == 0.9 and llm.kwargs["max_tokens"] == 512  # 没覆盖的键继承；None 不覆盖
    assert "top_p" not in llm.kwargs


def test_cache_keeps_one_instance_per_effective_params(recording, monkeypatch):
    """共用同一模型、参数不同的两个智能体交替对话：各自复用一个实例，不互相把对方踢出缓存。"""
    built: list = []
    real_new = gateway._new_llm
    monkeypatch.setattr(gateway, "_new_llm", lambda model, params: built.append(params) or real_new(model, params))
    m = _model({"temperature": 0.2})
    for _ in range(3):
        a = build_llm(m, {"temperature": 0.9})
        b = build_llm(m, {})
    assert a is not b and len(built) == 2
    # 模型配置改了（updated_at 变）才换新实例
    build_llm(_model({"temperature": 0.3}, updated_at="2026-09-25T00:00:01"), {})
    assert len(built) == 3


@pytest.mark.parametrize("params", [{"temperature": 3}, {"top_p": 1.5}, {"max_tokens": 0}, {"foo": 1}, {"thinking": "maybe"}])
def test_agent_params_out_of_range_or_unknown_are_422_and_not_saved(client, auth_headers, model_id, params):
    body = _agent_body(model_id, params)
    r = client.post("/api/v1/agents", headers=auth_headers, json=body)
    if r.status_code == 200:  # 校验回归时会落库：先删掉再让断言失败，免得在共享库留垃圾、连带模型也删不掉
        client.delete(f"/api/v1/agents/{r.json()['id']}", headers=auth_headers)
    assert r.status_code == 422, r.text
    assert client.get("/api/v1/agents", headers=auth_headers, params={"q": body["name"]}).json()["total"] == 0


@pytest.mark.parametrize("field,value", [("default_params", {"temperature": 3}), ("default_params", {"foo": 1}), ("price_input", -1), ("price_output", -0.5)])
def test_model_params_and_price_out_of_range_are_422(client, auth_headers, field, value):
    body = {"name": "pytest-params-bad-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "http://upstream.test/v1",
            "api_key": "sk-test", "model_name": "x", "default_params": {}, field: value}
    r = client.post("/api/v1/models", headers=auth_headers, json=body)
    if r.status_code == 200:  # 同上：校验回归时先清掉再失败
        client.delete(f"/api/v1/models/{r.json()['id']}", headers=auth_headers)
    assert r.status_code == 422, r.text


def test_chat_and_workflow_agent_node_use_agent_params(client, auth_headers, model_id, recording):
    agent = client.post("/api/v1/agents", headers=auth_headers, json=_agent_body(model_id, {"temperature": 0.9})).json()
    other = client.post("/api/v1/agents", headers=auth_headers, json=_agent_body(model_id, {})).json()
    wf = None
    try:
        for aid in (agent["id"], other["id"]):
            assert client.post(f"/api/v1/agents/{aid}/publish", headers=auth_headers).status_code == 200
        admin_id = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
        db = SessionLocal()
        try:
            conv_id, _ = chat_service.prepare_chat(db, admin_id, agent["id"], "你好")
            assert chat_service.build_chat_context(db, agent["id"], "你好", conv_id, role="admin").llm.kwargs["temperature"] == 0.9
            conv_other, _ = chat_service.prepare_chat(db, admin_id, other["id"], "你好")
            assert chat_service.build_chat_context(db, other["id"], "你好", conv_other, role="admin").llm.kwargs["temperature"] == 0.2
        finally:
            db.close()
        graph = {
            "nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "a", "type": "agent", "config": {"agent_id": agent["id"]}}, {"id": "e", "type": "end", "config": {}}],
            "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "e"}],
        }
        wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-params-wf", "description": "", "graph": graph}).json()
        r = client.post(f"/api/v1/workflows/{wf['id']}/run", headers=auth_headers, json={"input": "hi"})
        assert r.status_code == 200 and r.json()["status"] == "success", r.text
        cached = [llm for llm in gateway._LLM_CACHE.values() if llm.kwargs.get("temperature") == 0.9]
        assert cached, "工作流智能体节点没有按智能体参数构造模型"
    finally:
        if wf:
            client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)
        for aid in (agent["id"], other["id"]):
            client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)
