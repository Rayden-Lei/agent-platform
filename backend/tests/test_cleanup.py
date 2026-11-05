"""测试残留回收的用例（tests/cleanup.py）。

为什么单独测它：这个模块的作用是"删数据"，一旦判据写错就是事故。这里用真实业务数据做护栏
——断言回收**不碰**名字正常的行，比断言它删掉了该删的更重要。
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Agent, ModelConfig
from app.db.session import SessionLocal
from tests import cleanup


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def model_row(db):
    """一个名字带 pytest- 前缀的模型（agents.model_id 是 RESTRICT，造智能体要先有它）。

    缓存 id 而不是留着实例：回收用例会把行删掉，commit 后实例过期，再访问 m.id 会抛
    ObjectDeletedError。
    """
    m = ModelConfig(name="pytest-cleanup-model-" + _uid(), provider="openai", api_base="https://example.com/v1",
                    api_key_enc="x", model_name="m", default_params={})
    db.add(m)
    db.commit()
    model_id = m.id
    db.expunge_all()
    yield model_id
    db.query(Agent).filter(Agent.model_id == model_id).delete()
    db.commit()
    db.query(ModelConfig).filter(ModelConfig.id == model_id).delete()
    db.commit()


def _make_agent(db, name: str, model_id: int) -> int:
    """造一条智能体，返回 id（不返回实例：回收后实例会过期）。"""
    a = Agent(name=name, description="", system_prompt="x", model_id=model_id,
              params={}, kb_ids=[], tool_ids=[], status="draft")
    db.add(a)
    db.commit()
    agent_id = a.id
    db.expunge_all()
    return agent_id


def test_purges_prefixed_rows(db, model_row):
    """名字带 pytest- 前缀、且在时间窗内的行被删掉，返回各表计数。"""
    agent_id = _make_agent(db, "pytest-cleanup-agent-" + _uid(), model_row)

    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    deleted = cleanup.purge_test_rows(db, since)
    db.commit()

    assert deleted.get("agents", 0) >= 1
    assert db.query(Agent).filter(Agent.id == agent_id).count() == 0


def test_keeps_rows_created_before_window(db, model_row):
    """时间窗之前的行不删：回收只负责本次会话，历史残留要人工确认。"""
    agent_id = _make_agent(db, "pytest-cleanup-old-" + _uid(), model_row)

    # 窗口设在未来：等价于"这行建于窗口之前"
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    deleted = cleanup.purge_test_rows(db, future)
    db.commit()

    assert deleted.get("agents", 0) == 0
    assert db.query(Agent).filter(Agent.id == agent_id).count() == 1
    db.query(Agent).filter(Agent.id == agent_id).delete()
    db.commit()


def test_keeps_rows_without_prefix(db, model_row):
    """名字不带 pytest- 前缀的行一律不碰——这是保护真实业务数据的最后一道。"""
    agent_id = _make_agent(db, "cleanup-keep-agent-" + _uid(), model_row)

    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    cleanup.purge_test_rows(db, since)
    db.commit()

    assert db.query(Agent).filter(Agent.id == agent_id).count() == 1
    db.query(Agent).filter(Agent.id == agent_id).delete()
    db.commit()


def test_keeps_rows_still_referenced_by_real_data(db, model_row):
    """pytest- 模型被一条**非测试**智能体引用时，模型保留：删它会撞 RESTRICT、打断真实数据。"""
    real_id = _make_agent(db, "cleanup-real-agent-" + _uid(), model_row)

    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    deleted = cleanup.purge_test_rows(db, since)
    db.commit()

    assert deleted.get("models", 0) == 0          # 模型没被删
    assert deleted.get("_skipped", 0) >= 1        # 计进了跳过数
    assert db.query(ModelConfig).filter(ModelConfig.id == model_row).count() == 1

    db.query(Agent).filter(Agent.id == real_id).delete()
    db.commit()


def test_one_blocked_row_does_not_block_siblings(db):
    """同表里一行被真实数据引用，不能连累另一行也删不掉（逐行删的理由）。"""
    blocked = ModelConfig(name="pytest-cleanup-blocked-" + _uid(), provider="openai",
                          api_base="https://example.com/v1", api_key_enc="x", model_name="m", default_params={})
    free = ModelConfig(name="pytest-cleanup-free-" + _uid(), provider="openai",
                       api_base="https://example.com/v1", api_key_enc="x", model_name="m", default_params={})
    db.add_all([blocked, free])
    db.commit()
    blocked_id, free_id = blocked.id, free.id
    db.expunge_all()
    real_id = _make_agent(db, "cleanup-holder-agent-" + _uid(), blocked_id)

    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    deleted = cleanup.purge_test_rows(db, since)
    db.commit()

    assert db.query(ModelConfig).filter(ModelConfig.id == blocked_id).count() == 1   # 被引用的留着
    assert db.query(ModelConfig).filter(ModelConfig.id == free_id).count() == 0     # 同表另一行照删
    assert deleted.get("_skipped", 0) >= 1

    db.query(Agent).filter(Agent.id == real_id).delete()
    db.commit()
    db.query(ModelConfig).filter(ModelConfig.id.in_([blocked_id, free_id])).delete()
    db.commit()


def test_aborts_over_row_limit(db, model_row, monkeypatch):
    """命中行数超上限时抛 CleanupAborted，且一行都不删。"""
    agent_id = _make_agent(db, "pytest-cleanup-limit-" + _uid(), model_row)
    monkeypatch.setattr(cleanup, "ROW_LIMIT", 0)
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(cleanup.CleanupAborted):
        cleanup.purge_test_rows(db, since)
    db.rollback()
    # 一行都没删
    assert db.query(Agent).filter(Agent.id == agent_id).count() == 1
    db.query(Agent).filter(Agent.id == agent_id).delete()
    db.commit()


def test_delete_order_respects_restrict_fk():
    """agents 必须排在 models / workflows 之前：它们之间是 RESTRICT，顺序反了会直接报外键错误。"""
    tables = [t for t, _ in cleanup._DELETE_ORDER]
    assert tables.index("agents") < tables.index("models")
    assert tables.index("agents") < tables.index("workflows")
    assert tables.index("conversations") < tables.index("agents")
    assert tables.index("users") == len(tables) - 1
