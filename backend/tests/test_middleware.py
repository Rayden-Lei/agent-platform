"""中间件层（docs/16 P1）：装配、系统提示变换、轮数守卫、观察者隔离。

纯函数与内存对象，不碰数据库与网络。
"""
from langchain_core.messages import AIMessage

from app.services.middleware import (
    ChatMiddleware,
    RoundGuardMiddleware,
    ToolRoundsExceeded,
    apply_system_prompt,
    chain_hooks,
    notify_event,
)


class _PostM1(ChatMiddleware):
    def post_model_hook(self):
        return lambda state: {"a": 1}

    def on_system_prompt(self, prompt: str) -> str:
        return prompt + "|m1"


class _PostM2(ChatMiddleware):
    def post_model_hook(self):
        return lambda state: {"b": 2}


class _Empty(ChatMiddleware):
    """什么都不实现：装配时应当被完全跳过。"""


class _ExplodingObserver(ChatMiddleware):
    def on_event(self, event: dict) -> None:
        raise RuntimeError("观察者炸了")


def _state_with_tool_calls(count: int) -> dict:
    return {"messages": [AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": f"c{i}"}]) for i in range(count)]}


def test_chain_hooks_returns_none_when_nothing_implements_it():
    assert chain_hooks([_Empty(), None], "pre_model_hook") is None
    assert chain_hooks([], "post_model_hook") is None


def test_chain_hooks_merges_returns_of_every_middleware():
    run = chain_hooks([_PostM1(), _PostM2()], "post_model_hook")
    assert run({}) == {"a": 1, "b": 2}


def test_chain_hooks_skips_middlewares_without_the_point():
    run = chain_hooks([_Empty(), _PostM1()], "post_model_hook")
    assert run({}) == {"a": 1}


def test_system_prompt_transforms_run_in_order():
    assert apply_system_prompt([_PostM1(), _Empty()], "base") == "base|m1"
    assert apply_system_prompt([_Empty()], "base") == "base"


def test_round_guard_passes_under_limit():
    guard = RoundGuardMiddleware(2).post_model_hook()
    assert guard(_state_with_tool_calls(2)) == {}


def test_round_guard_raises_over_limit():
    guard = RoundGuardMiddleware(2).post_model_hook()
    try:
        guard(_state_with_tool_calls(3))
    except ToolRoundsExceeded as e:
        assert e.max_rounds == 2 and "超过最大工具调用轮数（2）" in str(e)
    else:  # pragma: no cover - 失败路径
        raise AssertionError("超过上限应当抛 ToolRoundsExceeded")


def test_round_guard_counts_only_messages_with_tool_calls():
    """历史消息只有文本（chat_service._history_to_messages），不带 tool_calls 的不算轮数。"""
    state = {"messages": [AIMessage(content="历史"), AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c1"}])]}
    assert RoundGuardMiddleware(1).post_model_hook()(state) == {}


def test_observer_failure_is_logged_not_raised():
    """观察者（trace）出错不能打断对话。"""
    notify_event([_ExplodingObserver()], {"type": "delta", "content": "x"})  # 不抛即通过


class _FakeModel:
    id = 7
    name = "pytest-model"


def test_trace_middleware_builds_llm_step_with_usage():
    """llm 步骤要带这次调用的 usage 与工具名——这是不能用纯事件观察者替代的原因。"""
    from app.services.chat_events import StreamState
    from app.services.middleware import TraceMiddleware

    tracer = TraceMiddleware(_FakeModel())
    state = StreamState()
    state.usage_by_call["call-1"] = {"total_tokens": 12}
    tracer.on_chunk("call-1", "你", ["echo"])
    tracer.on_chunk("call-1", "好", [])
    step = tracer.close_call(state)
    assert step["type"] == "llm" and step["name"] == "pytest-model"
    assert step["output"] == {"content_chars": 2, "tool_calls": ["echo"]}
    assert step["meta"]["usage"] == {"total_tokens": 12}
    assert step["meta"]["model_id"] == 7
    assert step["meta"]["first_token_ms"] is not None


def test_trace_middleware_tool_status_counts_inner_error():
    from app.services.middleware import TraceMiddleware

    tracer = TraceMiddleware(_FakeModel())
    ok = tracer.tool_step("echo", {"a": 1}, '{"result": "ok"}')
    bad = tracer.tool_step("echo", {}, '{"error": "boom"}')
    plain = tracer.tool_step("echo", {}, "纯文本结果")
    assert ok["status"] == "success" and ok["input"] == {"a": 1}
    assert bad["status"] == "error"
    assert plain["status"] == "success"  # 非 JSON 按成功记


def test_trace_middleware_close_call_without_open_call_returns_none():
    from app.services.chat_events import StreamState
    from app.services.middleware import TraceMiddleware

    assert TraceMiddleware(_FakeModel()).close_call(StreamState()) is None
