"""工作流计量的回归用例（docs/15 WF-19，2026-11-18 补齐）。

审计发现：工作流运行从不写 runs.token_usage 与 runs.cost，运营统计里工作流的 token 与成本恒为 0。
根因是引擎的 agent 节点拿到模型返回后把 usage 丢掉，收尾只写 status / output。

这里钉住三件事：
1. 引擎把每个智能体节点的用量按模型累计进 state（并行分支也不会丢，靠 reducer）；
2. 收尾按**各模型自己的单价**分别折算再相加 —— 一张图里混用两个模型时，
   拿其中一个的单价乘总量会得出一个既不是 A 也不是 B 的数字；
3. 模型没配单价时 cost 保持为空（不编一个 0 出来），用量照常记。
"""
from __future__ import annotations

import pytest

from app.db.models import ModelConfig, Run, User
from app.db.session import SessionLocal
from app.services import run_service
from app.workflow.engine import _merge_usage, _usage_of


# --------------------------------------------------------------------------- 引擎侧：用量采集与累加

class _Msg:
    """最小化的模型返回替身：只需要 usage_metadata。"""

    def __init__(self, usage):
        self.usage_metadata = usage


def test_usage_of_reads_usage_metadata():
    assert _usage_of(_Msg({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})) == {
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def test_usage_of_falls_back_to_response_metadata():
    """部分厂商把用量放在 response_metadata.token_usage 里（OpenAI 原生格式）。"""
    class _Msg2:
        usage_metadata = None
        response_metadata = {"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    assert _usage_of(_Msg2()) == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}


def test_usage_of_returns_empty_when_absent():
    """取不到就返回空：宁可不记，也不编一个 0（0 会被当成"确实没花 token"，缺失能看出是没采集到）。"""
    assert _usage_of(_Msg(None)) == {}
    assert _usage_of(_Msg({})) == {}
    assert _usage_of(object()) == {}


def test_merge_usage_sums_per_model():
    """同一模型的多次调用累加；不同模型分开记。并行分支两个节点同超步写入时靠这个 reducer 合并。"""
    first = _merge_usage({}, {"1": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    second = _merge_usage(first, {"1": {"prompt_tokens": 20, "completion_tokens": 1, "total_tokens": 21}})
    assert second["1"] == {"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36}
    third = _merge_usage(second, {"2": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    assert set(third) == {"1", "2"}
    assert third["1"]["total_tokens"] == 36 and third["2"]["total_tokens"] == 2


def test_merge_usage_handles_none_and_missing_fields():
    """缺字段按 0 处理，None 输入不抛（检查点反序列化后可能是 None）。"""
    assert _merge_usage(None, None) == {}
    assert _merge_usage({}, {"3": {}})["3"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert _merge_usage({"4": {"prompt_tokens": 2}}, None)["4"]["prompt_tokens"] == 2


def test_aggregate_usage_sums_across_models():
    """runs.token_usage 的口径是三键合计；完全没用量时返回空字典（不是全 0 的字典）。"""
    total = run_service.aggregate_usage({"1": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                                        "2": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    assert total == {"prompt_tokens": 11, "completion_tokens": 6, "total_tokens": 17}
    assert run_service.aggregate_usage({}) == {}
    assert run_service.aggregate_usage(None) == {}


# --------------------------------------------------------------------------- 收尾侧：按模型单价折算

@pytest.fixture
def two_models(db_session):
    """两个单价不同的模型（元 / 百万 token）。"""
    cheap = ModelConfig(name="pytest-usage-cheap", provider="openai", api_base="https://pytest.invalid/v1",
                        api_key_enc="x", model_name="cheap", default_params={}, price_input=1.0, price_output=2.0)
    pricey = ModelConfig(name="pytest-usage-pricey", provider="openai", api_base="https://pytest.invalid/v1",
                         api_key_enc="x", model_name="pricey", default_params={}, price_input=10.0, price_output=20.0)
    db_session.add_all([cheap, pricey])
    db_session.commit()
    try:
        yield cheap, pricey
    finally:
        db_session.query(ModelConfig).filter(ModelConfig.name.like("pytest-usage-%")).delete(synchronize_session=False)
        db_session.commit()


@pytest.fixture
def db_session():
    """独立会话：这组用例直接操作 ORM，不走 HTTP。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _user(db) -> User:
    user = db.query(User).filter(User.username == "admin").first()
    assert user is not None
    return user


def test_finalize_uses_each_models_own_price(db_session, two_models):
    """混用两个模型时，成本 = 各自用量 × 各自单价之和，model_id 归属用量最大的那个。"""
    cheap, pricey = two_models
    run = run_service.create_run(db_session, "workflow", _user(db_session).id, workflow_id=None,
                                 input_data={}, source="ui")
    try:
        usage_by_model = {
            str(cheap.id): {"prompt_tokens": 1_000_000, "completion_tokens": 0, "total_tokens": 1_000_000},
            str(pricey.id): {"prompt_tokens": 0, "completion_tokens": 100_000, "total_tokens": 100_000},
        }
        assert run_service.finalize_run(db_session, run, "success", usage_by_model=usage_by_model) is True
        db_session.refresh(run)
        # 1.0 元/百万 × 1M = 1.0；20 元/百万 × 0.1M = 2.0；合计 3.0
        assert run.cost == pytest.approx(3.0), run.cost
        assert run.token_usage == {"prompt_tokens": 1_000_000, "completion_tokens": 100_000, "total_tokens": 1_100_000}
        # 归属到用量最大的模型（100 万 token 的那个）
        assert run.model_id == cheap.id
    finally:
        db_session.query(Run).filter(Run.id == run.id).delete(synchronize_session=False)
        db_session.commit()


def test_finalize_without_prices_leaves_cost_empty(db_session):
    """模型没配单价：用量照记，cost 为空 —— 不编一个 0 出来（0 会被统计当成"确实没花钱"）。"""
    model = ModelConfig(name="pytest-usage-noprice", provider="openai", api_base="https://pytest.invalid/v1",
                        api_key_enc="x", model_name="noprice", default_params={})
    db_session.add(model)
    db_session.commit()
    run = run_service.create_run(db_session, "workflow", _user(db_session).id, workflow_id=None,
                                 input_data={}, source="ui")
    try:
        run_service.finalize_run(db_session, run, "success", usage_by_model={
            str(model.id): {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        db_session.refresh(run)
        assert run.token_usage["total_tokens"] == 150
        assert run.cost is None
    finally:
        db_session.query(Run).filter(Run.id == run.id).delete(synchronize_session=False)
        db_session.query(ModelConfig).filter(ModelConfig.id == model.id).delete(synchronize_session=False)
        db_session.commit()


def test_finalize_is_idempotent_for_usage(db_session, two_models):
    """已收尾的运行再收一次：不覆盖首次结果（流式对话已 done 后客户端断开又会触发一次取消收尾）。"""
    cheap, _ = two_models
    run = run_service.create_run(db_session, "workflow", _user(db_session).id, workflow_id=None,
                                 input_data={}, source="ui")
    try:
        run_service.finalize_run(db_session, run, "success", usage_by_model={
            str(cheap.id): {"prompt_tokens": 1000, "completion_tokens": 0, "total_tokens": 1000}})
        db_session.refresh(run)
        first_cost = run.cost
        assert run_service.finalize_run(db_session, run, "failed", usage_by_model={
            str(cheap.id): {"prompt_tokens": 999999, "completion_tokens": 0, "total_tokens": 999999}}) is False
        db_session.refresh(run)
        assert run.status == "success"
        assert run.cost == first_cost
        assert run.token_usage["total_tokens"] == 1000
    finally:
        db_session.query(Run).filter(Run.id == run.id).delete(synchronize_session=False)
        db_session.commit()
