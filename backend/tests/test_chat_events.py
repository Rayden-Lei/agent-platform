"""对话事件契约（docs/16 P0）：seq / reply_id、事件可重建消息、工具调用去重、结束原因。

纯函数与轻量构造，不碰数据库与 HTTP，所以不受开发库连通性影响。
"""
from app.core.exceptions import BizError
from app.services.chat_events import EventStream, StreamState, apply_event, reduce_events, tag_events
from app.services.chat_runner import ToolRoundsExceeded, _finished_reason


def test_event_stream_numbers_events_and_keeps_reply_id():
    stream = EventStream("run-7")
    first = stream.emit("delta", content="你")
    second = stream.emit("delta", content="好")
    assert [first["seq"], second["seq"]] == [0, 1]
    assert {first["reply_id"], second["reply_id"]} == {"run-7"}
    assert first["type"] == "delta" and second["content"] == "好"


def test_reduce_rebuilds_message_from_events():
    events = list(tag_events([
        {"type": "citations", "citations": [{"chunk_id": 1}]},
        {"type": "delta", "content": "答"},
        {"type": "delta", "content": "案"},
        {"type": "tool_call", "id": "c1", "name": "天气", "arguments": {"city": "北京"}, "state": "running"},
        {"type": "tool_result", "tool_call_id": "c1", "content": "晴", "state": "done"},
        {"type": "done", "usage": {"total_tokens": 9}, "finished_reason": "completed"},
    ], "run-1"))
    assert [e["seq"] for e in events] == list(range(6))
    msg = reduce_events(events)
    assert msg["content"] == "答案"
    assert msg["citations"] == [{"chunk_id": 1}]
    assert msg["tool_calls"] == [
        {"id": "c1", "name": "天气", "args": {"city": "北京"}, "status": "done", "result": "晴"},
    ]
    assert msg["usage"] == {"total_tokens": 9}
    assert msg["finished_reason"] == "completed"


def test_duplicate_tool_call_events_collapse_to_one_call():
    """一次工具调用可能先由完整 chunk 报一次、再由 ToolMessage 报一次，消息里只能有一条。"""
    msg = reduce_events([
        {"type": "tool_call", "id": "c1", "name": "t", "arguments": {"a": 1}, "state": "running"},
        {"type": "tool_call", "id": "c1", "name": "t", "arguments": {"a": 2}, "state": "running"},
        {"type": "tool_result", "tool_call_id": "c1", "content": "ok", "state": "done"},
    ])
    assert len(msg["tool_calls"]) == 1
    assert msg["tool_calls"][0]["args"] == {"a": 2}
    assert msg["tool_calls"][0]["status"] == "done"


def test_tool_error_state_and_orphan_result():
    msg = reduce_events([{"type": "tool_result", "tool_call_id": "c9", "content": "boom", "state": "error"}])
    assert msg["tool_calls"][0]["status"] == "error"
    assert msg["tool_calls"][0]["result"] == "boom"


def test_debug_only_events_do_not_pollute_message():
    msg = reduce_events([
        {"type": "prompt", "system_prompt": "x"},
        {"type": "trace", "step": {"name": "retrieve"}},
        {"type": "delta", "content": "a"},
    ])
    assert msg["content"] == "a" and msg["tool_calls"] == [] and msg["citations"] == []


def test_error_event_sets_finished_reason():
    msg = reduce_events([{"type": "error", "message": "x", "finished_reason": "exceed_max_iters"}])
    assert msg["finished_reason"] == "exceed_max_iters"


def test_finished_reason_distinguishes_round_limit():
    assert _finished_reason(ToolRoundsExceeded(8)) == "exceed_max_iters"
    assert _finished_reason(BizError(400, "x")) == "error"


def test_stored_result_kept_out_of_event_view():
    """实时路径可以把落库口径（8000 字）放进 state，重放只能拿到事件里的展示口径（200 字）。"""
    state = StreamState()
    apply_event(state, {"type": "tool_call", "id": "c1", "name": "t", "arguments": {}})
    apply_event(state, {"type": "tool_result", "tool_call_id": "c1", "content": "短", "state": "done"}, stored_result="长" * 8000)
    assert state.tool_calls[0]["result"] == "长" * 8000
    replayed = reduce_events([{"type": "tool_call", "id": "c1", "name": "t", "arguments": {}},
                              {"type": "tool_result", "tool_call_id": "c1", "content": "短", "state": "done"}])
    assert replayed["tool_calls"][0]["result"] == "短"


def test_llm_usage_events_rebuild_usage_without_done():
    """事件流里有了每次调用的用量，没有 done 事件也能算出本轮 token。"""
    msg = reduce_events([
        {"type": "llm_usage", "call_id": "c1", "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
        {"type": "llm_usage", "call_id": "c2", "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22}},
    ])
    assert msg["usage"] == {"prompt_tokens": 30, "completion_tokens": 4, "total_tokens": 34}


def test_done_usage_wins_over_llm_usage():
    """done 的汇总优先：它是收尾时算好的那份，避免两份口径打架。"""
    msg = reduce_events([
        {"type": "llm_usage", "call_id": "c1", "usage": {"total_tokens": 12}},
        {"type": "done", "usage": {"total_tokens": 99}, "finished_reason": "completed"},
    ])
    assert msg["usage"] == {"total_tokens": 99}


def test_delta_call_id_does_not_affect_rebuilt_content():
    msg = reduce_events([
        {"type": "delta", "call_id": "c1", "content": "你"},
        {"type": "delta", "call_id": "c2", "content": "好"},
    ])
    assert msg["content"] == "你好"
