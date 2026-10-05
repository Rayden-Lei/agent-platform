"""对话入口与执行器（docs/15 3.5.3，FR-044）：入参与会话归属在写库之前拒绝、工具轮数上限、错误脱敏、单个会话接口。

模型全用桩（tests/fakes）：把 chat_service.build_chat_context 换成返回桩模型的版本，不发任何网络请求。
"""
import json
import uuid

import pytest

from app.config import settings
from app.db.models import Conversation, Message, Run
from app.db.session import SessionLocal
from app.services import chat_service
from tests.fakes import AnswerModel as _AnswerModel
from tests.fakes import ToolLoopModel as _ToolLoopModel
from tests.fakes import use_llm as _use_llm


def _events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def _chat(client, headers, agent_id: int, message: str, conversation_id: int | None = None):
    return client.post(f"/api/v1/agents/{agent_id}/chat", headers=headers, json={"message": message, "conversation_id": conversation_id})


def _runs_of(agent_id: int) -> list[Run]:
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.agent_id == agent_id).order_by(Run.id).all()
    finally:
        db.close()


@pytest.fixture
def make_agent(client, auth_headers):
    """造已发布的智能体；模型只用来满足外键，对话时换成桩。"""
    model = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-runner-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "https://example.com/v1",
        "api_key": "sk-test", "model_name": "m", "default_params": {},
    }).json()
    created: list[int] = []

    def _make() -> dict:
        a = client.post("/api/v1/agents", headers=auth_headers, json={
            "name": "pytest-runner-" + uuid.uuid4().hex[:6], "description": "", "system_prompt": "测试", "model_id": model["id"],
            "params": {}, "kb_ids": [], "tool_ids": [], "workflow_id": None,
        }).json()
        assert client.post(f"/api/v1/agents/{a['id']}/publish", headers=auth_headers).status_code == 200
        created.append(a["id"])
        return a

    yield _make
    for aid in created:
        client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)
    client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


def test_chat_streams_answer_then_done(client, auth_headers, make_agent, monkeypatch):
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["你好 世界"])))
    events = _events(_chat(client, auth_headers, agent["id"], "打个招呼"))
    assert "".join(e["content"] for e in events if e["type"] == "delta") == "你好 世界"
    assert events[-1]["type"] == "done"
    assert [r.status for r in _runs_of(agent["id"])] == ["success"]


def test_chat_via_api_key_is_recorded_with_key_id(client, auth_headers, make_agent, monkeypatch):
    """运行来源区分登录对话与 API Key 调用（OP-09a）：此前 Key 发起的对话也记成 chat，按 Key 筛不到。"""
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["一", "二"])))
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-runner-key", "quota": 5, "agent_ids": [agent["id"]]}).json()
    try:
        _chat(client, {"Authorization": "Bearer " + key["key"]}, agent["id"], "用 Key 问")
        _chat(client, auth_headers, agent["id"], "登录后问")
        runs = _runs_of(agent["id"])
        assert [(r.source, r.api_key_id) for r in runs] == [("api_key", key["id"]), ("chat", None)]
    finally:
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)


def test_blank_message_rejected_before_any_write(client, auth_headers, make_agent, monkeypatch):
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["不该走到模型"])))  # 万一校验回归也不去请求外网
    r = _chat(client, auth_headers, agent["id"], "   \n ")
    assert r.status_code == 400 and r.json()["detail"] == "消息不能为空"
    assert _runs_of(agent["id"]) == []


@pytest.mark.parametrize("length", [0, settings.CHAT_MESSAGE_MAX_CHARS + 1])
def test_empty_or_oversized_message_is_422_and_writes_nothing(client, auth_headers, make_agent, monkeypatch, length):
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["不该走到模型"])))
    r = _chat(client, auth_headers, agent["id"], "字" * length)
    assert r.status_code == 422, r.text
    assert _runs_of(agent["id"]) == []


def test_conversation_of_another_agent_is_404_and_untouched(client, auth_headers, make_agent, monkeypatch):
    """会话必须属于该智能体：否则智能体 A 能接着写 B 的会话。"""
    agent_a, agent_b = make_agent(), make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["B 的回答"])))
    done = _events(_chat(client, auth_headers, agent_b["id"], "问 B"))[-1]
    conv_b = done["conversation_id"]
    r = _chat(client, auth_headers, agent_a["id"], "冒用 B 的会话", conversation_id=conv_b)
    assert r.status_code == 404 and r.json()["detail"] == "会话不存在或不属于该智能体"
    db = SessionLocal()
    try:
        assert db.query(Message).filter(Message.conversation_id == conv_b).count() == 2
    finally:
        db.close()
    assert _runs_of(agent_a["id"]) == []


def test_tool_rounds_over_limit_end_with_error_and_failed_run(client, auth_headers, make_agent, monkeypatch):
    agent = make_agent()
    monkeypatch.setattr(settings, "TOOL_CALL_MAX_ROUNDS", 2)
    _use_llm(monkeypatch, _ToolLoopModel())
    events = _events(_chat(client, auth_headers, agent["id"], "一直调工具"))
    assert events[-1]["type"] == "error" and "超过最大工具调用轮数（2）" in events[-1]["message"]
    assert sum(1 for e in events if e["type"] == "tool_result") == 2  # 允许的两轮照常执行
    runs = _runs_of(agent["id"])
    assert [r.status for r in runs] == ["failed"] and "超过最大工具调用轮数（2）" in runs[0].error


def test_internal_error_is_not_leaked_to_caller(client, auth_headers, make_agent, monkeypatch):
    agent = make_agent()

    def _boom(*args, **kwargs):
        raise RuntimeError("http://10.0.0.5:9000 connection refused")

    monkeypatch.setattr(chat_service, "build_chat_context", _boom)
    r = _chat(client, auth_headers, agent["id"], "触发内部错误")
    error = _events(r)[-1]
    assert error["type"] == "error" and "10.0.0.5" not in error["message"]
    assert r.headers["x-request-id"] in error["message"]  # 带 trace_id 便于对日志
    runs = _runs_of(agent["id"])
    assert [x.status for x in runs] == ["failed"] and "10.0.0.5" in runs[0].error  # 原文只进运行记录


def test_get_conversation_returns_list_item_shape_and_hides_others(client, auth_headers, make_agent, monkeypatch):
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["好的"])))
    conv_id = _events(_chat(client, auth_headers, agent["id"], "建个会话"))[-1]["conversation_id"]
    r = client.get(f"/api/v1/conversations/{conv_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["agent_id"] == agent["id"] and r.json()["message_count"] == 2
    assert client.get("/api/v1/conversations/999999999", headers=auth_headers).status_code == 404
    username = "pytest-runner-caller-" + uuid.uuid4().hex[:6]
    caller = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "caller123", "role": "caller"}).json()
    try:
        token = client.post("/api/v1/auth/login", json={"username": username, "password": "caller123"}).json()["token"]
        assert client.get(f"/api/v1/conversations/{conv_id}", headers={"Authorization": "Bearer " + token}).status_code == 404
    finally:
        client.delete(f"/api/v1/users/{caller['id']}", headers=auth_headers)


def test_conversation_row_belongs_to_the_agent_it_was_created_with(client, auth_headers, make_agent, monkeypatch):
    """回归：新会话的 agent_id 就是发起对话的智能体（会话归属校验依赖它）。"""
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["嗯"])))
    conv_id = _events(_chat(client, auth_headers, agent["id"], "你好"))[-1]["conversation_id"]
    db = SessionLocal()
    try:
        assert db.get(Conversation, conv_id).agent_id == agent["id"]
    finally:
        db.close()
