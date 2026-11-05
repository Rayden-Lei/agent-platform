"""对话分类型（docs/17 §3，P1）：模型对话、智能体对话、工作流对话共用一个会话外壳。

覆盖四件事：
1. 三条对话入口各自建出正确类型的会话与运行记录（kind、归属列、run_type、model_id）；
2. 会话归属按「类型 + 对象」双校验——跨类型、跨对象一律 404，不泄露存在性；
3. 工作流对话的"一句话 → 入参"规则与不可对话的拒绝口径（这一步是本次最容易被写错的业务规则）；
4. 权限：模型对话与工作流对话只对 admin / developer 开放，caller 403。

模型一律用桩（tests/fakes.use_llm 只换智能体对话的上下文装配，模型对话用 monkeypatch 换 model_chat.build_model_context），
不发任何网络请求；工作流用 start → end 的最小图，不依赖智能体节点。
"""
import json
import uuid

import pytest
from langchain_core.messages import HumanMessage

from app.core.exceptions import BizError
from app.db.models import Conversation, Message, Run
from app.db.session import SessionLocal
from app.services import model_chat, workflow_chat
from app.services.chat_service import ChatContext
from tests.fakes import FAKE_MODEL, AnswerModel, use_llm


def _events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def _delta(events: list[dict]) -> str:
    return "".join(e["content"] for e in events if e["type"] == "delta")


@pytest.fixture
def make_model(client, auth_headers):
    """造一个启用的模型行（对话时换成桩，只用来满足外键与可用性判定）。"""
    model = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-kind-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "https://example.com/v1",
        "api_key": "sk-test", "model_name": "m", "default_params": {},
    }).json()
    yield model
    client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


@pytest.fixture
def make_agent(client, auth_headers, make_model):
    """造已发布的智能体（模型沿用 make_model，对话时换成桩）。用来验证"跨类型会话不能互串"。"""
    created: list[int] = []

    def _make() -> dict:
        a = client.post("/api/v1/agents", headers=auth_headers, json={
            "name": "pytest-kind-agent-" + uuid.uuid4().hex[:6], "description": "", "system_prompt": "测试",
            "model_id": make_model["id"], "params": {}, "kb_ids": [], "tool_ids": [], "workflow_id": None,
        }).json()
        assert client.post(f"/api/v1/agents/{a['id']}/publish", headers=auth_headers).status_code == 200
        created.append(a["id"])
        return a

    yield _make
    for aid in created:
        client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)


@pytest.fixture
def make_workflow(client, auth_headers):
    """造一个 start → end 的最小工作流：开始节点声明一个文本变量 input，结束节点把它的值当输出。

    不挂智能体节点，所以整条链路不碰模型，用例可以离线跑。
    """
    created: list[int] = []

    def _make(variables=None) -> dict:
        graph = {
            "nodes": [
                {"id": "s", "type": "start", "config": {"variables": variables if variables is not None else [
                    {"name": "input", "type": "text", "description": "对话消息"}]}},
                {"id": "e", "type": "end", "config": {"outputs": [{"name": "reply", "ref": "{{start.input}}"}]}},
            ],
            "edges": [{"from": "s", "to": "e"}],
        }
        w = client.post("/api/v1/workflows", headers=auth_headers, json={
            "name": "pytest-kind-wf-" + uuid.uuid4().hex[:6], "description": "", "graph": graph})
        assert w.status_code == 200, w.text
        created.append(w.json()["id"])
        return w.json()

    yield _make
    for wid in created:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def _use_model_llm(monkeypatch, llm, captured: list | None = None) -> None:
    """换掉模型对话的上下文装配：与生产同一套 ChatContext，只是模型是桩。"""
    def _build(db, model_id, message_text, conversation_id):
        if captured is not None:
            captured.append(model_id)
        return ChatContext(model=FAKE_MODEL, llm=llm, tools=[], system_prompt="你是测试助手",
                           citations=[], history_messages=[HumanMessage(content=message_text)])

    monkeypatch.setattr(model_chat, "build_model_context", _build)


def _model_chat(client, headers, model_id: int, message: str, conversation_id: int | None = None):
    return client.post(f"/api/v1/models/{model_id}/chat", headers=headers,
                       json={"message": message, "conversation_id": conversation_id})


def _workflow_chat(client, headers, workflow_id: int, message: str, conversation_id: int | None = None):
    return client.post(f"/api/v1/workflows/{workflow_id}/chat", headers=headers,
                       json={"message": message, "conversation_id": conversation_id})


# ---------- 模型对话 ----------

def test_model_chat_streams_and_records_a_model_conversation(client, auth_headers, make_model, monkeypatch):
    _use_model_llm(monkeypatch, AnswerModel(messages=iter(["你好 模型"])))
    events = _events(_model_chat(client, auth_headers, make_model["id"], "打个招呼"))
    assert _delta(events) == "你好 模型"
    assert events[-1]["type"] == "done"
    conv_id = events[-1]["conversation_id"]

    db = SessionLocal()
    try:
        conv = db.get(Conversation, conv_id)
        # 三种归属列互斥（DB 约束同口径）：模型对话只填 model_id
        assert (conv.kind, conv.model_id, conv.agent_id, conv.workflow_id) == ("model", make_model["id"], None, None)
        run = db.query(Run).filter(Run.conversation_id == conv_id).one()
        # 运行记录按 chat 归集消耗：模型对话不是工作流，不该混进工作流运行列表
        assert (run.run_type, run.model_id, run.agent_id, run.source) == ("chat", make_model["id"], None, "chat")
        assert [m.role for m in db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.id)] == ["user", "assistant"]
    finally:
        db.close()


def test_model_chat_continues_the_same_conversation(client, auth_headers, make_model, monkeypatch):
    _use_model_llm(monkeypatch, AnswerModel(messages=iter(["一", "二"])))
    first = _events(_model_chat(client, auth_headers, make_model["id"], "第一句"))[-1]
    second = _events(_model_chat(client, auth_headers, make_model["id"], "第二句", first["conversation_id"]))[-1]
    assert second["conversation_id"] == first["conversation_id"]
    db = SessionLocal()
    try:
        assert db.query(Message).filter(Message.conversation_id == first["conversation_id"]).count() == 4
    finally:
        db.close()


def test_model_chat_rejects_disabled_model_before_writing(client, auth_headers, make_model, monkeypatch):
    _use_model_llm(monkeypatch, AnswerModel(messages=iter(["不该走到模型"])))
    client.post(f"/api/v1/models/{make_model['id']}/toggle", headers=auth_headers)  # 停用
    r = _model_chat(client, auth_headers, make_model["id"], "你好")
    assert r.status_code == 400 and r.json()["detail"] == "模型不可用"
    db = SessionLocal()
    try:
        assert db.query(Conversation).filter(Conversation.model_id == make_model["id"]).count() == 0
    finally:
        db.close()


def test_model_chat_cannot_continue_an_agent_conversation(client, auth_headers, make_agent, make_model, monkeypatch):
    """会话的类型与对象都要对得上：拿模型去续一个智能体会话必须 404，否则模型对话能读到别人的上下文。"""
    agent = make_agent()
    use_llm(monkeypatch, AnswerModel(messages=iter(["智能体的回答"])))
    conv_id = _events(client.post(f"/api/v1/agents/{agent['id']}/chat", headers=auth_headers,
                                  json={"message": "你好"}))[-1]["conversation_id"]
    _use_model_llm(monkeypatch, AnswerModel(messages=iter(["不该走到模型"])))
    r = _model_chat(client, auth_headers, make_model["id"], "冒用智能体会话", conv_id)
    assert r.status_code == 404 and r.json()["detail"] == "会话不存在或不属于该模型"


def test_model_chat_requires_admin_or_developer(client, caller_headers, make_model):
    """caller 只看到智能体对话（docs/17 §3.7），模型对话入口直接 403。"""
    assert _model_chat(client, caller_headers, make_model["id"], "你好").status_code == 403


# ---------- 工作流对话 ----------

def test_workflow_chat_runs_once_and_maps_nodes_to_tool_events(client, auth_headers, make_workflow):
    wf = make_workflow()
    events = _events(_workflow_chat(client, auth_headers, wf["id"], "帮我处理这句话"))
    types = [e["type"] for e in events]
    # 节点映射：开始、结束各一对 tool_call / tool_result；最终回答走 delta；最后 done
    assert types.count("tool_call") == 2 and types.count("tool_result") == 2
    assert types[-2:] == ["delta", "done"]
    assert _delta(events) == "帮我处理这句话"  # 结束节点把 start.input 原样当 reply
    assert [e["name"] for e in events if e["type"] == "tool_call"] == ["开始", "结束"]

    conv_id = events[-1]["conversation_id"]
    db = SessionLocal()
    try:
        conv = db.get(Conversation, conv_id)
        assert (conv.kind, conv.workflow_id, conv.agent_id, conv.model_id) == ("workflow", wf["id"], None, None)
        run = db.query(Run).filter(Run.conversation_id == conv_id).one()
        # 工作流对话的运行记录就是一次工作流运行：出现在该工作流的运行列表里，入参可追溯
        assert (run.run_type, run.workflow_id, run.source) == ("workflow", wf["id"], "chat")
        assert run.input["inputs"] == {"input": "帮我处理这句话"}
    finally:
        db.close()


def test_workflow_chat_each_turn_is_an_independent_run(client, auth_headers, make_workflow):
    """方案 c：会话只做历史展示，每轮一次独立运行（docs/17 §3.4）。"""
    wf = make_workflow()
    first = _events(_workflow_chat(client, auth_headers, wf["id"], "第一轮"))[-1]
    _workflow_chat(client, auth_headers, wf["id"], "第二轮", first["conversation_id"])
    db = SessionLocal()
    try:
        runs = db.query(Run).filter(Run.conversation_id == first["conversation_id"]).order_by(Run.id).all()
        assert len(runs) == 2 and all(r.run_type == "workflow" for r in runs)
        assert [r.input["inputs"] for r in runs] == [{"input": "第一轮"}, {"input": "第二轮"}]
        assert db.query(Message).filter(Message.conversation_id == first["conversation_id"]).count() == 4
    finally:
        db.close()


def test_workflow_without_text_input_variable_is_rejected(client, auth_headers, make_workflow):
    """没有文本变量就没有地方接消息，明确 400 而不是把消息丢掉继续跑。"""
    wf = make_workflow(variables=[])
    r = _workflow_chat(client, auth_headers, wf["id"], "你好")
    assert r.status_code == 400 and "没有声明文本输入变量" in r.json()["detail"]
    db = SessionLocal()
    try:
        assert db.query(Conversation).filter(Conversation.workflow_id == wf["id"]).count() == 0
    finally:
        db.close()


def test_workflow_with_multiple_text_variables_needs_one_named_input(client, auth_headers, make_workflow):
    """多个文本变量时平台不替你猜填哪个（docs/17 §3.4）：要么其中一个改名 input，要么去运行弹窗填。"""
    wf = make_workflow(variables=[{"name": "question", "type": "text"}, {"name": "tone", "type": "text"}])
    r = _workflow_chat(client, auth_headers, wf["id"], "你好")
    assert r.status_code == 400 and "请把其中一个改名为 input" in r.json()["detail"]


def test_workflow_with_extra_required_variable_is_rejected(client, auth_headers, make_workflow):
    """消息只填给消息变量，其余必填变量没人提供 → 明确报出是哪个，不静默丢参数。"""
    wf = make_workflow(variables=[{"name": "input", "type": "text"}, {"name": "lang", "type": "text"}])
    r = _workflow_chat(client, auth_headers, wf["id"], "你好")
    assert r.status_code == 400 and "lang" in r.json()["detail"]


def test_workflow_single_text_variable_takes_the_message_even_if_not_named_input(client, auth_headers, make_workflow):
    """只有一个文本变量时不必强制改名 input —— 单变量的工作流不用记第二条规则。"""
    wf = make_workflow(variables=[{"name": "question", "type": "text"}])
    events = _events(_workflow_chat(client, auth_headers, wf["id"], "单变量也能聊"))
    assert events[-1]["type"] == "done"


def test_workflow_chat_stops_at_human_review_without_finalizing(client, auth_headers, make_workflow):
    """人工审核节点：这轮对话结束、回答里给出审批指引，但运行记录留在 awaiting_review（不是终态），
    否则运行记录页的 resume 会被"该运行不在待审核状态"拒掉，文档承诺的审批路径就走不通。"""
    graph = {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text"}]}},
            {"id": "r", "type": "human_review", "config": {"instruction": "请确认"}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "r"}, {"from": "r", "to": "e"}],
    }
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={
        "name": "pytest-kind-review-" + uuid.uuid4().hex[:6], "description": "", "graph": graph}).json()
    try:
        events = _events(_workflow_chat(client, auth_headers, wf["id"], "走一遍"))
        assert events[-1]["type"] == "done" and events[-1]["finished_reason"] == "interrupted"
        assert "人工审核" in _delta(events)
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.conversation_id == events[-1]["conversation_id"]).one()
            assert run.status == "awaiting_review" and run.finished_at is None
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)


def test_workflow_chat_cannot_continue_a_model_conversation(client, auth_headers, make_model, make_workflow, monkeypatch):
    _use_model_llm(monkeypatch, AnswerModel(messages=iter(["模型的回答"])))
    conv_id = _events(_model_chat(client, auth_headers, make_model["id"], "你好"))[-1]["conversation_id"]
    wf = make_workflow()
    r = _workflow_chat(client, auth_headers, wf["id"], "冒用模型会话", conv_id)
    assert r.status_code == 404 and r.json()["detail"] == "会话不存在或不属于该工作流"


def test_workflow_chat_requires_admin_or_developer(client, caller_headers, make_workflow):
    wf = make_workflow()
    assert _workflow_chat(client, caller_headers, wf["id"], "你好").status_code == 403


# ---------- 会话列表按类型过滤 ----------

def test_conversation_list_filters_by_kind_and_target(client, auth_headers, make_agent, make_model, make_workflow, monkeypatch):
    use_llm(monkeypatch, AnswerModel(messages=iter(["智能体"])))
    agent = make_agent()
    agent_conv = _events(client.post(f"/api/v1/agents/{agent['id']}/chat", headers=auth_headers,
                                     json={"message": "问智能体"}))[-1]["conversation_id"]
    _use_model_llm(monkeypatch, AnswerModel(messages=iter(["模型"])))
    model_conv = _events(_model_chat(client, auth_headers, make_model["id"], "问模型"))[-1]["conversation_id"]
    wf = make_workflow()
    wf_conv = _events(_workflow_chat(client, auth_headers, wf["id"], "问工作流"))[-1]["conversation_id"]

    def listed(**params):
        return {c["id"] for c in client.get("/api/v1/conversations", headers=auth_headers, params=params).json()["items"]}

    assert listed(kind="agent", target_id=agent["id"]) == {agent_conv}
    assert listed(kind="model", target_id=make_model["id"]) == {model_conv}
    assert listed(kind="workflow", target_id=wf["id"]) == {wf_conv}
    # 只给 kind 不限对象：这一类对话全部列出
    assert listed(kind="model") == {model_conv} and listed(kind="workflow") == {wf_conv}
    # 列表项的归属口径是 kind + target_id + target_name
    item = next(c for c in client.get("/api/v1/conversations", headers=auth_headers,
                                      params={"kind": "workflow", "target_id": wf["id"]}).json()["items"] if c["id"] == wf_conv)
    assert item["target_name"] == wf["name"]


def test_conversation_list_rejects_target_without_kind(client, auth_headers):
    """只给对象不给类型时不知道该查哪一列，明确 400 而不是猜。"""
    r = client.get("/api/v1/conversations", headers=auth_headers, params={"target_id": 1})
    assert r.status_code == 400 and "kind" in r.json()["detail"]


# ---------- 业务规则的纯函数部分 ----------

def test_message_variable_rules():
    """消息变量规则：input 优先 → 唯一文本变量 → 其余不可对话（前端按同一套逻辑禁用输入框）。"""
    def vars_of(*items):
        return {"nodes": [{"id": "s", "type": "start", "config": {"variables": list(items)}}]}

    assert workflow_chat.message_variable(vars_of({"name": "input", "type": "text"}))[0] == "input"
    assert workflow_chat.message_variable(vars_of({"name": "q", "type": "text"}))[0] == "q"
    # 有 input 时即便还有别的文本变量也用它
    assert workflow_chat.message_variable(vars_of({"name": "a", "type": "text"}, {"name": "input", "type": "text"}))[0] == "input"
    # 数字变量不算可承载消息
    assert workflow_chat.message_variable(vars_of({"name": "n", "type": "number"}))[0] is None
    name, reason = workflow_chat.message_variable(vars_of({"name": "a", "type": "text"}, {"name": "b", "type": "text"}))
    assert name is None and "a、b" in reason


def test_build_inputs_fills_message_and_defaults():
    graph = {"nodes": [{"id": "s", "type": "start", "config": {"variables": [
        {"name": "input", "type": "text"},
        {"name": "days", "type": "integer", "default": 7},
    ]}}]}
    assert workflow_chat.build_inputs(graph, "你好") == {"input": "你好", "days": 7}


def test_reply_text_prefers_reply_key_then_plain_text():
    assert workflow_chat.reply_of({"reply": "回答", "other": 1}) == "回答"
    assert workflow_chat.reply_of({"only": "唯一输出"}) == "唯一输出"
    assert workflow_chat.reply_of("纯文本") == "纯文本"
    assert workflow_chat.reply_of({"a": 1, "b": 2}).strip().startswith("{")
    assert workflow_chat.answer_of([{"reply": "最后一处"}], interrupted=False) == "最后一处"
    assert "人工审核" in workflow_chat.answer_of([], interrupted=True)


def test_check_constraint_blocks_two_owners(client, auth_headers):
    """DB 兜底：一行会话不能既绑模型又绑智能体（应用层漏判时在写入处直接失败）。"""
    db = SessionLocal()
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
    try:
        db.add(Conversation(kind="agent", agent_id=None, model_id=None, user_id=me, title="pytest-kind-bad"))
        with pytest.raises(Exception) as info:
            db.commit()
        assert "ck_conversations_kind" in str(info.value)
    finally:
        db.rollback()
        db.close()
