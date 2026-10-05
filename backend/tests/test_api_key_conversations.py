"""会话通道隔离、终端用户与消息幂等（docs/15 3.7.1，AC-028 ② ③ 的会话部分、⑦）。模型换成桩，其余链路走真实代码。

作用域本身见 test_api_key_scopes.py。
"""
import json
import uuid

import pytest

from app.db.models import Conversation, Message, Run
from app.db.session import SessionLocal
from app.services import chat_service
from tests.fakes import AnswerModel

KEYS = "/api/v1/api-keys"
CONV = "/api/v1/conversations"


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def setup(client, auth_headers, monkeypatch):
    """一个已发布的智能体、两个都授权了它的 Key；模型换成桩（每次构建上下文给一个新桩）。结束时删掉。"""
    monkeypatch.setattr(chat_service, "build_llm", lambda model, params=None: AnswerModel(messages=iter(["第一次的回答"])))
    model = client.post("/api/v1/models", headers=auth_headers, json={"name": "pytest-conv-model-" + _uid(), "provider": "openai",
                                                                     "api_base": "http://upstream.test/v1", "api_key": "sk-test", "model_name": "x", "default_params": {}}).json()
    agent = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-conv-agent-" + _uid(), "description": "", "system_prompt": "你是助手", "model_id": model["id"]}).json()
    assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).status_code == 200
    keys = [client.post(KEYS, headers=auth_headers, json={"name": "pytest-conv-key-" + _uid(), "agent_ids": [agent["id"]]}).json() for _ in range(2)]
    yield {"agent": agent["id"], "a": {"Authorization": "Bearer " + keys[0]["key"]}, "b": {"Authorization": "Bearer " + keys[1]["key"]}}
    for k in keys:
        client.delete(f"{KEYS}/{k['id']}", headers=auth_headers)
    client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
    client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


def _chat(client, headers, agent_id: int, **body):
    return client.post(f"/api/v1/agents/{agent_id}/chat", headers=headers, json={"message": "你好", **body})


def _events(resp) -> list[dict]:
    return [json.loads(p[6:]) for p in resp.text.split("\n\n") if p.startswith("data: ")]


def _done(client, headers, agent_id: int, **body) -> dict:
    r = _chat(client, headers, agent_id, **body)
    assert r.status_code == 200, r.text
    done = _events(r)[-1]
    assert done["type"] == "done", done
    return done


def _ids(client, headers, **params) -> set:
    r = client.get(CONV, headers=headers, params={"page_size": 100, **params})
    assert r.status_code == 200, r.text
    return {c["id"] for c in r.json()["items"]}


def _counts(conversation_id: int) -> tuple[int, int]:
    db = SessionLocal()
    try:
        return (db.query(Message).filter(Message.conversation_id == conversation_id).count(),
                db.query(Run).filter(Run.conversation_id == conversation_id).count())
    finally:
        db.close()


# ---------- 会话通道（AC-028 ②） ----------

def test_key_and_ui_conversations_do_not_see_each_other(client, auth_headers, setup):
    """Key 只看到自己（且同一 end_user）建的会话，看不到归属人在界面里的；界面也看不到 Key 建的。
    2026-10-05 前 Key 等同归属人登录，能列出、读、删归属人的全部会话。"""
    ui = _done(client, auth_headers, setup["agent"])["conversation_id"]
    by_a = _done(client, setup["a"], setup["agent"])["conversation_id"]
    by_a_alice = _done(client, setup["a"], setup["agent"], end_user="alice")["conversation_id"]
    by_b = _done(client, setup["b"], setup["agent"])["conversation_id"]
    assert ui in _ids(client, auth_headers) and not {by_a, by_a_alice, by_b} & _ids(client, auth_headers)
    assert _ids(client, setup["a"]) == {by_a}  # 不传 end_user 只看没有终端用户的
    assert _ids(client, setup["a"], end_user="alice") == {by_a_alice}
    assert _ids(client, setup["b"]) == {by_b}
    for cid in (ui, by_b, by_a_alice):  # 读、读消息、删都按同一个归属判定
        assert client.get(f"{CONV}/{cid}", headers=setup["a"]).status_code == 404
        assert client.get(f"{CONV}/{cid}/messages", headers=setup["a"]).status_code == 404
        assert client.delete(f"{CONV}/{cid}", headers=setup["a"]).status_code == 404
    assert client.get(f"{CONV}/{by_a}", headers=auth_headers).status_code == 404
    db = SessionLocal()
    try:
        row = db.get(Conversation, by_a_alice)
        assert (row.channel, row.end_user) == ("api", "alice") and row.api_key_id is not None
        assert db.get(Conversation, ui).channel == "ui"
    finally:
        db.close()


# ---------- 续聊的归属与入参（AC-028 ③ 的会话部分） ----------

def test_cannot_continue_someone_elses_conversation(client, auth_headers, setup):
    by_a = _done(client, setup["a"], setup["agent"], end_user="alice")["conversation_id"]
    before = _counts(by_a)
    for headers, end_user in ((setup["b"], "alice"), (setup["a"], "bob"), (setup["a"], None), (auth_headers, None)):
        body = {"conversation_id": by_a, **({"end_user": end_user} if end_user else {})}
        r = _chat(client, headers, setup["agent"], **body)
        assert r.status_code == 404 and r.json()["detail"] == "会话不存在或不属于该智能体", (end_user, r.text)
    assert _counts(by_a) == before  # 不新增消息与运行记录
    assert _done(client, setup["a"], setup["agent"], conversation_id=by_a, end_user="alice")["conversation_id"] == by_a


@pytest.mark.parametrize("end_user", ["has space", "x" * 65, "", "中文"])
def test_bad_end_user_is_422(client, setup, end_user):
    assert _chat(client, setup["a"], setup["agent"], end_user=end_user).status_code == 422
    assert client.get(CONV, headers=setup["a"], params={"end_user": end_user}).status_code == 422


def test_login_request_cannot_send_end_user(client, auth_headers, setup):
    r = _chat(client, auth_headers, setup["agent"], end_user="alice")
    assert r.status_code == 400 and "end_user" in r.json()["detail"]
    assert client.get(CONV, headers=auth_headers, params={"end_user": "alice"}).status_code == 400


# ---------- 消息幂等（AC-028 ⑦） ----------

def test_same_client_message_id_replays_the_first_answer(client, setup):
    """续聊时重发同一个 client_message_id：消息数与运行记录数都不增加，回放首次的回答、message_id 与 run_id。"""
    cid = _done(client, setup["a"], setup["agent"])["conversation_id"]
    first = _done(client, setup["a"], setup["agent"], conversation_id=cid, client_message_id="req-001")
    counts = _counts(cid)
    again = _chat(client, setup["a"], setup["agent"], conversation_id=cid, client_message_id="req-001")
    events = _events(again)
    assert [e["type"] for e in events] == ["delta", "done"]
    assert events[0]["content"] == "第一次的回答"
    assert (events[-1]["message_id"], events[-1]["run_id"], events[-1]["replayed"]) == (first["message_id"], first["run_id"], True)
    assert _counts(cid) == counts
    other = _done(client, setup["a"], setup["agent"], conversation_id=cid, client_message_id="req-002")  # 换一个 id 正常新一轮
    assert other["run_id"] != first["run_id"] and _counts(cid) == (counts[0] + 2, counts[1] + 1)


def test_replay_while_first_is_running_is_409_and_failed_first_replays_its_error(client, setup):
    cid = _done(client, setup["a"], setup["agent"])["conversation_id"]
    first = _done(client, setup["a"], setup["agent"], conversation_id=cid, client_message_id="req-run")
    db = SessionLocal()
    try:
        db.get(Run, first["run_id"]).status = "running"  # 模拟首次仍在生成
        db.commit()
    finally:
        db.close()
    busy = _chat(client, setup["a"], setup["agent"], conversation_id=cid, client_message_id="req-run")
    assert busy.status_code == 409 and "正在处理" in busy.json()["detail"]
    db = SessionLocal()
    try:
        run = db.get(Run, first["run_id"])
        run.status, run.error = "failed", "模型调用失败：上游超时"
        db.commit()
    finally:
        db.close()
    events = _events(_chat(client, setup["a"], setup["agent"], conversation_id=cid, client_message_id="req-run"))
    assert [e["type"] for e in events] == ["error"] and events[0]["message"].startswith("模型调用失败：上游超时")


def test_unique_index_backs_up_concurrent_duplicates(client, setup):
    """并发的同一条撞上部分唯一索引：数据库兜底，同一会话里同一个 client_message_id 只能有一条用户消息。"""
    cid = _done(client, setup["a"], setup["agent"])["conversation_id"]
    _done(client, setup["a"], setup["agent"], conversation_id=cid, client_message_id="req-dup")
    db = SessionLocal()
    try:
        db.add(Message(conversation_id=cid, role="user", content="并发的第二条", client_message_id="req-dup"))
        with pytest.raises(Exception, match="uq_messages_conversation_client_message"):
            db.commit()
    finally:
        db.rollback()
        db.close()
