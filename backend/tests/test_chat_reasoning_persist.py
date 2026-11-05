"""思维链落库与历史回放：messages.reasoning 列。

2026-11-05 使用者反馈"思考过程怎么也没了"：reasoning 只随 SSE 推给前端、不落库，
刷新或切回会话后折叠行就消失。这里守住三件事：
① 落库时把 state.reasoning 写进 messages.reasoning；
② 没有思维链时存 NULL 而不是空串，前端才好按有无内容决定是否渲染；
③ 历史接口原样返回，前端 toChatMessages 映射成 msg.reasoning。

不走 HTTP 夹具：直接调服务层，不依赖登录口令与限流。
会话表有 ck_conversations_kind 约束（agent 类必须带 agent_id），所以取库里一个真实智能体挂上。
"""
import pytest

from app.db.models import Agent, Conversation, User
from app.db.session import SessionLocal
from app.services import chat_service, conversation_service


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def owner(db):
    """会话要挂真实外键：返回 (user_id, agent_id)，缺数据时跳过。"""
    uid = db.query(User.id).order_by(User.id).limit(1).scalar()
    aid = db.query(Agent.id).order_by(Agent.id).limit(1).scalar()
    if uid is None or aid is None:
        pytest.skip("库里缺少用户或智能体")
    return uid, aid


@pytest.fixture
def conversation(db, owner):
    uid, aid = owner
    conv = Conversation(user_id=uid, kind="agent", agent_id=aid, channel="ui", title="pytest-reasoning")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    yield conv
    db.delete(conv)  # 消息随外键级联删除
    db.commit()


def test_save_assistant_message_persists_reasoning(db, conversation):
    msg = chat_service.save_assistant_message(db, conversation.id, "答案", [], {}, [], None, reasoning="先想一下再答")
    db.refresh(msg)
    assert msg.reasoning == "先想一下再答"


def test_empty_reasoning_is_stored_as_null(db, conversation):
    """没有思维链的模型不该存空串：历史接口才好用 None 判断"没有思考过程"。"""
    msg = chat_service.save_assistant_message(db, conversation.id, "答案", [], {}, [], None, reasoning="")
    db.refresh(msg)
    assert msg.reasoning is None


def test_history_returns_reasoning(db, conversation, owner):
    """历史接口要把 reasoning 带出来，前端刷新后才能回放折叠行。"""
    uid, _ = owner
    chat_service.save_assistant_message(db, conversation.id, "答案", [], {}, [], None, reasoning="推理内容")
    caller = conversation_service.Caller(channel="ui", user_id=uid)
    rows = conversation_service.list_messages(db, conversation.id, caller)
    assert rows[-1]["reasoning"] == "推理内容"


def test_history_reasoning_is_none_when_absent(db, conversation, owner):
    uid, _ = owner
    chat_service.save_assistant_message(db, conversation.id, "答案", [], {}, [], None)
    caller = conversation_service.Caller(channel="ui", user_id=uid)
    rows = conversation_service.list_messages(db, conversation.id, caller)
    assert rows[-1]["reasoning"] is None
