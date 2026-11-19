"""模型对话（services/model_chat.py）的上下文装配与拒绝路径。

与 test_chat_kinds.py 的分工：那个文件把 build_model_context 打桩，走接口验证"流式事件与运行记录"；
这里直接对服务层下断言，专攻**历史消息装配**与**写库之前的每一道拒绝**。

为什么值得单独测：
- _history 的"去掉最后一条用户消息"规则写错，模型会收到两条一模一样的用户消息（回答质量莫名变差，
  但没有任何报错）；
- 历史条数上限写错，长会话会把上下文撑爆；
- 拒绝必须发生在写库之前，否则一次非法请求就留下一条空运行记录。
"""
from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.core.exceptions import BizError
from app.core.security import encrypt_secret
from app.db.models import Conversation, Message, ModelConfig
from app.db.session import SessionLocal
from app.services import model_chat
from app.services.conversation_service import KIND_MODEL


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def admin(db):
    from app.db.models import User

    return db.query(User).filter(User.username == "admin").first()


@pytest.fixture
def caller(admin):
    from app.services.conversation_service import caller_for

    return caller_for(admin)


@pytest.fixture
def model(db, admin):
    """造一个可用的对话模型；结束时删掉（conversations 先删，model_id 是 RESTRICT）。"""
    m = ModelConfig(name="pytest-mc-model-" + uuid.uuid4().hex[:6], provider="openai",
                    api_base="http://upstream.test/v1", api_key_enc=encrypt_secret("sk-pytest"),
                    model_name="x", default_params={}, is_enabled=True)
    db.add(m)
    db.commit()
    yield m
    for conv in db.query(Conversation).filter(Conversation.model_id == m.id).all():
        db.query(Message).filter(Message.conversation_id == conv.id).delete()
        db.delete(conv)
    db.commit()
    db.delete(m)
    db.commit()


def _seed(db, conversation_id: int, rows: list[tuple[str, str]]) -> None:
    for role, content in rows:
        db.add(Message(conversation_id=conversation_id, role=role, content=content))
    db.commit()


def _new_conversation(db, model_id: int, title: str = "pytest-mc") -> Conversation:
    conv = Conversation(kind=KIND_MODEL, model_id=model_id, title=title, user_id=1)
    db.add(conv)
    db.commit()
    return conv


# --------------------------------------------------------------------------- 历史装配

def test_history_drops_the_duplicated_current_message(db, model):
    """本轮用户消息已落库：最后一条与它相同时必须去掉，否则模型收到两条一样的用户消息。"""
    conv = _new_conversation(db, model.id)
    _seed(db, conv.id, [("user", "第一句"), ("assistant", "回答一"), ("user", "第二句")])
    msgs = model_chat._history(db, conv.id, "第二句")
    assert [m.content for m in msgs] == ["第一句", "回答一", "第二句"]
    assert type(msgs[-1]).__name__ == "HumanMessage"


def test_history_keeps_last_message_when_it_differs(db, model):
    """最后一条与当前消息不同（比如上一轮失败、没落用户消息）：不能误删。"""
    conv = _new_conversation(db, model.id)
    _seed(db, conv.id, [("user", "旧问题"), ("assistant", "旧回答")])
    msgs = model_chat._history(db, conv.id, "新问题")
    assert [m.content for m in msgs] == ["旧问题", "旧回答", "新问题"]


def test_history_maps_roles(db, model):
    """user/assistant 映射成对应消息类型；其余角色（tool/system）不进历史。"""
    conv = _new_conversation(db, model.id)
    _seed(db, conv.id, [("user", "q"), ("assistant", "a"), ("tool", "工具结果")])
    msgs = model_chat._history(db, conv.id, "next")
    assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage", "HumanMessage"]


def test_history_respects_max_messages(db, model, monkeypatch):
    """历史只取最近 N 条：不设限时长会话会把上下文撑爆。"""
    monkeypatch.setattr(settings, "CHAT_HISTORY_MAX_MESSAGES", 2)
    conv = _new_conversation(db, model.id)
    _seed(db, conv.id, [("user", "1"), ("assistant", "2"), ("user", "3"), ("assistant", "4")])
    msgs = model_chat._history(db, conv.id, "5")
    # 最近 2 条（"3"、"4"）+ 当前消息
    assert [m.content for m in msgs] == ["3", "4", "5"]


def test_history_on_empty_conversation_is_just_the_message(db, model):
    conv = _new_conversation(db, model.id)
    msgs = model_chat._history(db, conv.id, "只有这句")
    assert [m.content for m in msgs] == ["只有这句"]


# --------------------------------------------------------------------------- 上下文

def test_build_context_has_no_tools_and_neutral_prompt(db, model):
    """模型对话刻意不挂工具、不检索：它是"试模型"，不是智能体。"""
    conv = _new_conversation(db, model.id)
    ctx = model_chat.build_model_context(db, model.id, "hi", conv.id)
    assert ctx.tools == []
    assert ctx.citations == []
    assert ctx.system_prompt == model_chat.DEFAULT_SYSTEM_PROMPT
    assert ctx.model.id == model.id


def test_build_context_missing_conversation_is_404(db, model):
    with pytest.raises(BizError) as ei:
        model_chat.build_model_context(db, model.id, "hi", 99999999)
    assert ei.value.status_code == 404
    assert "会话不存在" in ei.value.detail


def test_build_context_rejects_disabled_model(db, model):
    """流式执行时才被停用也要给明确错误：不能用"模型不可用"以外的含糊文案。"""
    model.is_enabled = False
    db.commit()
    with pytest.raises(BizError) as ei:
        model_chat.build_model_context(db, model.id, "hi", 1)
    assert ei.value.status_code == 400
    assert "模型不可用" in ei.value.detail


# --------------------------------------------------------------------------- 准备阶段

def test_prepare_rejects_blank_message(db, caller, model):
    with pytest.raises(BizError) as ei:
        model_chat.prepare_model_chat(db, caller, model.id, "   ")
    assert ei.value.status_code == 400
    assert "消息不能为空" in ei.value.detail


def test_prepare_rejects_unknown_model(db, caller):
    with pytest.raises(BizError) as ei:
        model_chat.prepare_model_chat(db, caller, 99999999, "hi")
    assert ei.value.status_code == 400
    assert "模型不可用" in ei.value.detail


def test_prepare_rejects_disabled_model_before_writing(db, caller, model):
    """停用的模型必须在写库之前拒：否则每次被拒的请求都留下一条空运行记录。"""
    from app.db.models import Run

    model.is_enabled = False
    db.commit()
    before = db.query(Run).count()
    with pytest.raises(BizError):
        model_chat.prepare_model_chat(db, caller, model.id, "hi")
    assert db.query(Run).count() == before


def test_prepare_creates_conversation_and_run(db, caller, model):
    prepared, replay = model_chat.prepare_model_chat(db, caller, model.id, "你好")
    assert replay is None
    conv = db.get(Conversation, prepared.conversation_id)
    assert conv.kind == KIND_MODEL and conv.model_id == model.id
    assert conv.title  # 标题取自首条消息
    from app.db.models import Run

    run = db.get(Run, prepared.run_id)
    assert run.run_type == "chat" and run.model_id == model.id and run.agent_id is None


def test_prepare_continues_the_same_conversation(db, caller, model):
    first, _ = model_chat.prepare_model_chat(db, caller, model.id, "第一句")
    second, _ = model_chat.prepare_model_chat(db, caller, model.id, "第二句", first.conversation_id)
    assert second.conversation_id == first.conversation_id


def test_prepare_cannot_continue_another_models_conversation(db, caller, model):
    """会话归属不可混用：拿别的模型的会话 id 续聊必须 404（否则能读写别人的对话）。"""
    other = ModelConfig(name="pytest-mc-other-" + uuid.uuid4().hex[:6], provider="openai",
                        api_base="http://upstream.test/v1", api_key_enc=encrypt_secret("sk-pytest"),
                        model_name="x", default_params={}, is_enabled=True)
    db.add(other)
    db.commit()
    try:
        first, _ = model_chat.prepare_model_chat(db, caller, model.id, "属于 model 的会话")
        with pytest.raises(BizError) as ei:
            model_chat.prepare_model_chat(db, caller, other.id, "冒用", first.conversation_id)
        assert ei.value.status_code == 404
    finally:
        for conv in db.query(Conversation).filter(Conversation.model_id == other.id).all():
            db.query(Message).filter(Message.conversation_id == conv.id).delete()
            db.delete(conv)
        db.commit()
        db.delete(other)
        db.commit()


def test_duplicate_client_message_id_while_running_is_409(db, caller, model):
    """上一轮还没结束就重投同一个 client_message_id：409 让它等，**不能**回放一个还没产生的结果。

    这条与"已完成后回放"是幂等键的两个阶段（见 chat_turn._replay_of）：
    运行中重投是"别急"，已完成重投才是"给你上次的答案"。
    """
    first, _ = model_chat.prepare_model_chat(db, caller, model.id, "只问一次", client_message_id="cid-1")
    with pytest.raises(BizError) as ei:
        model_chat.prepare_model_chat(db, caller, model.id, "只问一次",
                                      first.conversation_id, client_message_id="cid-1")
    assert ei.value.status_code == 409
    assert "正在处理" in ei.value.detail


def test_duplicate_client_message_id_after_completion_replays(db, caller, model):
    """运行已结束、再投同一个 client_message_id：回放首次结果，不重复落消息、不重复调模型。"""
    from app.db.models import Run
    from app.services import run_service

    first, _ = model_chat.prepare_model_chat(db, caller, model.id, "只问一次", client_message_id="cid-2")  # noqa: E501
    run = db.get(Run, first.run_id)
    run_service.finalize_run(db, run, "success", output={"content": "首次回答"})
    db.commit()

    second, replay = model_chat.prepare_model_chat(db, caller, model.id, "只问一次",
                                                   first.conversation_id, client_message_id="cid-2")
    assert second is None
    assert replay is not None
    assert replay.conversation_id == first.conversation_id
    assert replay.run_id == first.run_id
    assert replay.status == "success"
    assert db.get(Run, first.run_id).status == "success"
