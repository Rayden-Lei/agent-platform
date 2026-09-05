"""对话摘要持久化（`12-差距补齐开发计划.md` 2.1，FR-031）：按批折叠、落库、失败降级、级联删除。

摘要模型一律 mock（带调用计数的假 LLM），不发网络请求；会话与消息直接写开发库并在用例结束时清理。
"""
import logging
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import settings
from app.db.models import Conversation, Message
from app.db.session import SessionLocal
from app.model_gateway import breaker
from app.services import chat_service

STUB = SimpleNamespace(id=999002, name="pytest-summary")
MAX, BATCH = 20, 10


class _CountingLLM:
    def __init__(self, reply: str = "摘要内容", fail: bool = False):
        self.calls: list = []
        self.reply, self.fail = reply, fail

    def invoke(self, prompt):
        self.calls.append(prompt)
        if self.fail:
            raise RuntimeError("摘要模型故障")
        return AIMessage(content=self.reply)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def conversation(client, auth_headers, db, monkeypatch):
    """一条属于 admin 的空会话；固定窗口与批大小，用例结束后删除（级联删消息）。"""
    monkeypatch.setattr(settings, "CHAT_HISTORY_MAX_MESSAGES", MAX)
    monkeypatch.setattr(settings, "CHAT_SUMMARY_BATCH_MESSAGES", BATCH)
    breaker.reset()
    user_id = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
    conv = Conversation(user_id=user_id, title="pytest-summary")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    conv_id = conv.id  # 用例可能已把会话删掉（级联用例），清理时不能再从实例上取 id
    try:
        yield conv
    finally:
        db.rollback()
        db.query(Conversation).filter(Conversation.id == conv_id).delete()
        db.commit()
        breaker.reset()


def _add_messages(db, conv: Conversation, count: int, content_len: int = 0) -> list[Message]:
    """追加 count 条 user / assistant 交替的消息，内容为"消息N"（可按 content_len 填充），返回本会话全部消息按 id 升序。"""
    existing = db.query(Message).filter(Message.conversation_id == conv.id).count()
    for i in range(existing, existing + count):
        content = f"消息{i + 1}"
        if content_len:
            content = content.ljust(content_len, "字")
        db.add(Message(conversation_id=conv.id, role="user" if i % 2 == 0 else "assistant", content=content))
    db.commit()
    return _rows(db, conv)


def _rows(db, conv: Conversation) -> list[Message]:
    return db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.id).all()


def _build(db, conv: Conversation, llm) -> list:
    return chat_service._build_history_messages(db, STUB, llm, conv, _rows(db, conv), settings.CHAT_HISTORY_MAX_MESSAGES)


def _fresh(conv_id: int) -> Conversation:
    """用新会话读库，确认摘要确实提交而不是只留在 session 里。"""
    session = SessionLocal()
    try:
        return session.get(Conversation, conv_id)
    finally:
        session.close()


def test_within_limit_does_not_call_summary(db, conversation):
    _add_messages(db, conversation, MAX)
    llm = _CountingLLM()
    messages = _build(db, conversation, llm)
    assert llm.calls == []
    assert len(messages) == MAX and not any(isinstance(m, SystemMessage) for m in messages)
    assert conversation.summary is None and conversation.summary_upto_message_id is None


def test_35_messages_first_round_summarizes_once_and_persists_upto(db, conversation):
    rows = _add_messages(db, conversation, 35)
    llm = _CountingLLM()
    messages = _build(db, conversation, llm)
    assert len(llm.calls) == 1
    # 摘要输入只含更早的 15 条，最近 20 条不参与
    assert "消息1\n" in llm.calls[0] and "消息15" in llm.calls[0] and "消息16" not in llm.calls[0]
    assert conversation.summary == "摘要内容"
    assert conversation.summary_upto_message_id == rows[14].id
    assert conversation.summary_updated_at is not None
    persisted = _fresh(conversation.id)
    assert persisted.summary == "摘要内容" and persisted.summary_upto_message_id == rows[14].id
    # 注入：[摘要] + 最近 20 条原文
    assert len(messages) == 1 + MAX
    assert isinstance(messages[0], SystemMessage) and "摘要内容" in messages[0].content
    assert messages[1].content == rows[15].content and messages[-1].content == rows[-1].content


def test_pending_below_batch_does_not_call_summary(db, conversation):
    _add_messages(db, conversation, 35)
    _build(db, conversation, _CountingLLM())
    upto_before = conversation.summary_upto_message_id
    rows = _add_messages(db, conversation, 4)  # 更早 19 条，待折叠 4 条 < 10
    llm = _CountingLLM()
    messages = _build(db, conversation, llm)
    assert llm.calls == []
    assert conversation.summary_upto_message_id == upto_before
    # 注入：[摘要] + 4 条未折叠原文 + 最近 20 条
    assert len(messages) == 1 + 4 + MAX
    assert isinstance(messages[0], SystemMessage)
    assert [m.content for m in messages[1:5]] == [r.content for r in rows[15:19]]
    assert isinstance(messages[1], AIMessage) and isinstance(messages[2], HumanMessage)  # 原文保留角色，不是拼成摘要


def test_pending_reaching_batch_summarizes_again_and_advances_upto(db, conversation):
    _add_messages(db, conversation, 35)
    _build(db, conversation, _CountingLLM())
    rows = _add_messages(db, conversation, 10)  # 更早 25 条，待折叠 10 条 = 批大小
    llm = _CountingLLM(reply="第二版摘要")
    messages = _build(db, conversation, llm)
    assert len(llm.calls) == 1
    # 第二次输入 = 旧摘要 + 本批 10 条，且不重复带上已折叠的消息
    prompt = llm.calls[0]
    assert "摘要内容" in prompt and "消息16" in prompt and "消息25" in prompt
    assert "消息15" not in prompt and "消息26" not in prompt
    assert conversation.summary == "第二版摘要"
    assert conversation.summary_upto_message_id == rows[24].id
    assert _fresh(conversation.id).summary == "第二版摘要"
    assert len(messages) == 1 + MAX and "第二版摘要" in messages[0].content


def test_summary_failure_keeps_state_and_injects_truncated_excerpt(db, conversation, caplog):
    _add_messages(db, conversation, 35, content_len=300)
    llm = _CountingLLM(fail=True)
    with caplog.at_level(logging.WARNING, logger="app.services.chat_service"):
        messages = _build(db, conversation, llm)
    assert len(llm.calls) == 1
    # 失败：不落库、边界不动
    assert conversation.summary is None and conversation.summary_upto_message_id is None
    assert _fresh(conversation.id).summary is None
    # 本轮待折叠消息退回截断原文（15 × 300 字远超上限）
    assert len(messages) == 1 + MAX
    excerpt = messages[0]
    assert isinstance(excerpt, SystemMessage) and "原文节选" in excerpt.content and "消息1" in excerpt.content
    assert len(excerpt.content) <= 60 + chat_service.SUMMARY_FALLBACK_CHARS
    assert any("历史摘要生成失败" in r.getMessage() for r in caplog.records)
    # 下一轮仍会再试
    llm_ok = _CountingLLM()
    _build(db, conversation, llm_ok)
    assert len(llm_ok.calls) == 1 and conversation.summary == "摘要内容"


def test_delete_conversation_cascades_messages(client, auth_headers, db, conversation):
    conv_id = conversation.id
    _add_messages(db, conversation, 25)
    _build(db, conversation, _CountingLLM())
    r = client.delete(f"/api/v1/conversations/{conv_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(Message).filter(Message.conversation_id == conv_id).count() == 0
    assert _fresh(conv_id) is None


def test_conversation_list_exposes_summary(client, auth_headers, db, conversation):
    conversation.summary = "列表可见的摘要"
    db.commit()
    r = client.get("/api/v1/conversations", headers=auth_headers, params={"page_size": 100})
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["id"] == conversation.id)
    assert item["summary"] == "列表可见的摘要"


def test_current_user_message_not_duplicated_in_context(client, auth_headers, db, conversation):
    """prepare_chat 已把本轮用户消息落库，build_chat_context 不能再把它当历史注入一次。"""
    mid = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-summary-model", "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {},
    }).json()["id"]
    agent = client.post("/api/v1/agents", headers=auth_headers, json={
        "name": "pytest-summary-agent", "description": "", "system_prompt": "你是助手", "model_id": mid,
    }).json()
    try:
        conversation.agent_id = agent["id"]
        db.add(Message(conversation_id=conversation.id, role="user", content="早先的问题"))
        db.add(Message(conversation_id=conversation.id, role="assistant", content="早先的回答"))
        db.add(Message(conversation_id=conversation.id, role="user", content="本轮的问题"))
        db.commit()
        ctx = chat_service.build_chat_context(db, agent["id"], "本轮的问题", conversation.id)
        contents = [m.content for m in ctx.history_messages]
        assert contents == ["早先的问题", "早先的回答", "本轮的问题"]
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{mid}", headers=auth_headers)
