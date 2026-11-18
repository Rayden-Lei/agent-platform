"""对话非流式（blocking）模式（docs/15 PB-10 / CH-15）。

三条对话入口（模型 / 智能体 / 工作流）都支持 `response_mode`：
- `streaming`（默认）= 现在的 SSE 事件流，既有调用方一行都不用改；
- `blocking` = 服务端跑完一整轮后返回一个 JSON，字段与流式 done 事件对齐，对接方不必解析 SSE。

这里钉住四件事：
1. blocking 的 content 与同一问题流式拼接的结果一致（同一个桩模型，两条路径产出同一段文本）；
2. blocking 返回的 conversation_id 能续聊；
3. 超时按"客户端中断"同一路径收尾：运行记录置 cancelled，不留永久 running；
4. 非法 response_mode 是 422（Literal 收窄），不是静默退回默认值。

模型全部打桩（tests/fakes），不发任何网络请求。
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.config import settings
from app.db.models import Run
from app.db.session import SessionLocal
from app.services import chat_runner
from tests.fakes import AnswerModel as _AnswerModel
from tests.fakes import use_llm as _use_llm


def _events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def _post(client, headers, agent_id: int, message: str, **extra):
    return client.post(f"/api/v1/agents/{agent_id}/chat", headers=headers, json={"message": message, **extra})


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
        "name": "pytest-blocking-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "https://example.com/v1",
        "api_key": "sk-test", "model_name": "m", "default_params": {},
    }).json()
    created: list[int] = []

    def _make() -> dict:
        a = client.post("/api/v1/agents", headers=auth_headers, json={
            "name": "pytest-blocking-" + uuid.uuid4().hex[:6], "description": "", "system_prompt": "测试",
            "model_id": model["id"], "params": {}, "kb_ids": [], "tool_ids": [],
        }).json()
        assert client.post(f"/api/v1/agents/{a['id']}/publish", headers=auth_headers).status_code == 200
        created.append(a["id"])
        return a

    yield _make
    for aid in created:
        client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)
    client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


# --------------------------------------------------------------------------- 正常返回

def test_blocking_returns_json_and_matches_streaming_content(client, auth_headers, make_agent, monkeypatch):
    """blocking 的 content 必须等于同一问题流式拼接的结果 —— 两条路径共用执行器，不该有两套文本。"""
    agent = make_agent()
    # 桩模型是"每次调用消费一条消息"，所以两条路径各给一个独立的模型实例、各一条同样的消息，
    # 断言的是"同一条消息经两条路径产出同一段文本"，而不是比较两个不同的模型。
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["你好 世界"])))
    streamed = _post(client, auth_headers, agent["id"], "打个招呼")
    assert streamed.headers["content-type"].startswith("text/event-stream")
    streamed_text = "".join(e["content"] for e in _events(streamed) if e["type"] == "delta")

    _use_llm(monkeypatch, _AnswerModel(messages=iter(["你好 世界"])))
    r = _post(client, auth_headers, agent["id"], "打个招呼", response_mode="blocking")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["content"] == streamed_text == "你好 世界"
    # 字段与流式 done 事件对齐（docs/15 PB-10 定死的那一组）
    for key in ("conversation_id", "message_id", "run_id", "content", "citations", "tool_calls", "usage", "status"):
        assert key in body, f"blocking 响应缺少字段 {key}"
    assert body["status"] == "success"
    assert body["run_id"] and body["message_id"] and body["conversation_id"]
    assert [r.status for r in _runs_of(agent["id"])] == ["success", "success"]


def test_blocking_conversation_can_be_continued(client, auth_headers, make_agent, monkeypatch):
    """blocking 返回的 conversation_id 能直接续聊（会话是真建了的，不是一次性的假返回）。"""
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["第一轮"])))
    first = _post(client, auth_headers, agent["id"], "第一问", response_mode="blocking").json()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["第二轮"])))
    second = _post(client, auth_headers, agent["id"], "第二问", conversation_id=first["conversation_id"],
                   response_mode="blocking").json()
    assert second["conversation_id"] == first["conversation_id"]
    assert second["content"] == "第二轮"
    assert second["run_id"] != first["run_id"]


def test_blocking_replay_of_same_client_message_id(client, auth_headers, make_agent, monkeypatch):
    """幂等回放同样支持 blocking：同一个 client_message_id 重发不会重复落消息、不会重复调模型。

    注意回放的判据是「**同一会话里**重复的 client_message_id」（chat_turn._replay_of 按会话查），
    所以第二次必须带上第一次返回的 conversation_id —— 不带就是开新会话，本来就不会回放。
    """
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["只该生成一次"])))
    payload = {"response_mode": "blocking", "client_message_id": "pytest-blocking-cm-" + uuid.uuid4().hex[:8]}
    first = client.post(f"/api/v1/agents/{agent['id']}/chat", headers=auth_headers,
                        json={"message": "问一次", **payload})
    assert first.status_code == 200, first.text
    # 回放不再调模型：桩模型只有一条消息，第二次真去调会拿到 StopIteration 而报错，
    # 所以"两次都成功且 message_id 相同"本身就证明了没有重复生成。
    again = client.post(f"/api/v1/agents/{agent['id']}/chat", headers=auth_headers,
                        json={"message": "问一次", "conversation_id": first.json()["conversation_id"], **payload})
    assert again.status_code == 200, again.text
    assert again.json()["message_id"] == first.json()["message_id"]
    assert again.json()["content"] == first.json()["content"]
    assert len(_runs_of(agent["id"])) == 1


# --------------------------------------------------------------------------- 负向

def test_invalid_response_mode_is_422(client, auth_headers, make_agent, monkeypatch):
    """response_mode 是 Literal：非法值 422，不静默退回 streaming（否则调用方以为拿到 JSON，实际是 SSE）。"""
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["不该走到模型"])))
    r = _post(client, auth_headers, agent["id"], "你好", response_mode="sync")
    assert r.status_code == 422, r.text
    assert _runs_of(agent["id"]) == []


def test_blocking_rejects_blank_message_before_any_write(client, auth_headers, make_agent, monkeypatch):
    """既有守卫在 blocking 下同样生效：空消息 400 且不写任何数据。"""
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["不该走到模型"])))
    r = _post(client, auth_headers, agent["id"], "   ", response_mode="blocking")
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "消息不能为空"
    assert _runs_of(agent["id"]) == []


def test_blocking_rejects_conversation_of_another_agent(client, auth_headers, make_agent, monkeypatch):
    """会话归属校验在 blocking 下同样生效（404 且不写数据）。"""
    agent_a, agent_b = make_agent(), make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["B 的回答"])))
    conv_b = _post(client, auth_headers, agent_b["id"], "问 B", response_mode="blocking").json()["conversation_id"]
    r = _post(client, auth_headers, agent_a["id"], "冒用 B 的会话", conversation_id=conv_b, response_mode="blocking")
    assert r.status_code == 404, r.text
    assert _runs_of(agent_a["id"]) == []


# --------------------------------------------------------------------------- 超时收尾

def test_blocking_timeout_finalizes_run_as_cancelled(client, auth_headers, make_agent, monkeypatch):
    """超时不能留永久 running：超时路径与"客户端中断"共用收尾（内容落库、运行置 cancelled）。

    把总超时调到 0 秒来触发：不需要真的等 300 秒，也不必造一个永远不返回的模型。
    """
    agent = make_agent()
    _use_llm(monkeypatch, _AnswerModel(messages=iter(["来不及生成"])))
    monkeypatch.setattr(settings, "CHAT_BLOCKING_TIMEOUT_SECONDS", 0)
    r = _post(client, auth_headers, agent["id"], "你好", response_mode="blocking")
    assert r.status_code == 504, r.text
    assert "超时" in r.json()["detail"]
    runs = _runs_of(agent["id"])
    assert len(runs) == 1
    assert runs[0].status == "cancelled", f"超时后运行记录必须是 cancelled，实际 {runs[0].status}"
    assert runs[0].finished_at is not None, "超时收尾必须写 finished_at，否则运行记录页看不出它已结束"


def test_blocking_error_event_becomes_http_status(client, auth_headers, make_agent, monkeypatch):
    """执行器发 error 事件时，blocking 用 HTTP 状态码表达（流式只能在事件里表达）。

    用"工具轮数超限"这条最确定的路径：桩模型一直要求调工具，超过 TOOL_CALL_MAX_ROUNDS 即以 error 结束。
    """
    from tests.fakes import ToolLoopModel

    agent = make_agent()
    _use_llm(monkeypatch, ToolLoopModel())
    r = _post(client, auth_headers, agent["id"], "一直调工具", response_mode="blocking")
    assert r.status_code == 400, r.text
    assert "工具" in r.json()["detail"]
    assert [run.status for run in _runs_of(agent["id"])] == ["failed"]


# --------------------------------------------------------------------------- 单元：错误状态码映射

@pytest.mark.parametrize("exc,expected", [
    (chat_runner.ToolRoundsExceeded("超过上限"), 400),
    (ValueError("意外错误"), 500),
])
def test_error_status_mapping(exc, expected):
    """error_status 的映射规则：业务错误带自己的状态码，轮数超限 400，其余 500。"""
    assert chat_runner.error_status(exc) == expected


def test_error_status_uses_biz_error_code():
    from app.core.exceptions import BizError

    assert chat_runner.error_status(BizError(503, "熔断中")) == 503
    assert chat_runner.error_status(BizError(400, "参数不对")) == 400


def test_blocking_timeout_is_configurable_and_positive():
    """超时是配置项且必须有正值：0 或负数会让每一次 blocking 请求立刻超时。"""
    assert isinstance(settings.CHAT_BLOCKING_TIMEOUT_SECONDS, int)
    assert settings.CHAT_BLOCKING_TIMEOUT_SECONDS > settings.MODEL_HTTP_TIMEOUT, (
        "总超时必须大于单次模型调用超时，否则正常的一轮工具调用就会被误判为超时")
