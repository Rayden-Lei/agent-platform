"""一轮对话的事件信封与消息重建（docs/16 P0）。

事件类型仍是前端认识的 6 类（调试另加 prompt / trace），只加三个字段，前端 switch 不用改：
- seq             本轮从 0 单调递增；SSE 的 id 行是 `<reply_id>:<seq>`，将来断点续传靠它
- reply_id        `run-<run_id>`，同一轮全一致，用来把事件归到同一条回答
- finished_reason completed / interrupted / exceed_max_iters / error，只在 done / error 上
工具事件另带 state：tool_call 是 running，tool_result 是 done（工具返回 {"error": ...} 或 LangChain
标了 error 时为 error）。

两条路径共用 apply_event：
- 实时：_agent_events 边产出边把结果累积进 StreamState（落库用），EventStream 只负责信封
- 重放：reduce_events 把一段事件序列还原成消息字段，校验"事件流能重建消息"这条契约

result 全文的边界：事件里的 content 是展示口径（TOOL_RESULT_PREVIEW_CHARS），落库的
tool_calls.result 是 TOOL_RESULT_STORE_CHARS，所以重建只能还原**展示视图**；result 的完整内容
以落库为准（docs/04 第 5 节）。这条差异是刻意的：不为了"完全一致"把 8000 字塞进每一帧。
"""
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

FINISHED_REASONS = ("completed", "interrupted", "exceed_max_iters", "error")

# 不进消息的事件：调试专用的提示词与调用链步骤
_NON_MESSAGE_EVENTS = frozenset({"prompt", "trace"})


@dataclass
class StreamState:
    """一轮执行中累积的结果。用量按模型调用分开记再相加：一轮里有工具调用时模型会被调多次，
    2026-09-29 前每来一次用量就整体覆盖，只剩最后一次调用的 token，前几次的用量与成本都丢了。"""

    content: str = ""
    tool_calls: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    usage_by_call: dict = field(default_factory=dict)
    final_usage: dict | None = None
    first_token_ms: int | None = None
    finished_reason: str | None = None

    def usage(self) -> dict:
        if self.final_usage is not None:
            return self.final_usage
        if not self.usage_by_call:
            return {}
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        return {k: sum(u.get(k, 0) for u in self.usage_by_call.values()) for k in keys}


@dataclass
class EventStream:
    """事件信封：给每条事件补 seq 与 reply_id，不改事件本身的类型与字段。"""

    reply_id: str
    seq: int = 0

    def emit(self, type_: str, **payload) -> dict:
        event = {"type": type_, "reply_id": self.reply_id, "seq": self.seq, **payload}
        self.seq += 1
        return event


def apply_event(state: StreamState, event: dict, *, stored_result: str | None = None) -> None:
    """把一个事件累积进消息状态。实时产出与事后重放共用这一份，避免两条路径各写一套。

    工具调用按 id 去重：一次工具调用可能先由完整 chunk 报一次、再由 ToolMessage 报一次，
    同 id 只保留一条（后到的参数与结果覆盖先到的）。
    stored_result：实时路径传落库口径的工具结果（TOOL_RESULT_STORE_CHARS），不传时用事件里的
    展示口径（TOOL_RESULT_PREVIEW_CHARS）。重放只能拿到事件里的那份。
    """
    type_ = event.get("type")
    if type_ == "delta":
        state.content += event.get("content") or ""
    elif type_ == "citations":
        state.citations = event.get("citations") or []
    elif type_ == "tool_call":
        call_id = event.get("id")
        item = _find_call(state.tool_calls, call_id)
        if item is None:
            state.tool_calls.append({
                "id": call_id,
                "name": event.get("name") or "工具",
                "args": event.get("arguments") or {},
                "status": event.get("state") or "running",
            })
        else:
            item["name"] = event.get("name") or item["name"]
            item["args"] = event.get("arguments") or item["args"]
    elif type_ == "tool_result":
        call_id = event.get("tool_call_id")
        result = stored_result if stored_result is not None else event.get("content")
        item = _find_call(state.tool_calls, call_id)
        if item is None:
            state.tool_calls.append({
                "id": call_id, "name": "工具", "args": {},
                "status": event.get("state") or "done", "result": result,
            })
        else:
            item["status"] = event.get("state") or "done"
            item["result"] = result
    elif type_ == "done":
        state.finished_reason = event.get("finished_reason") or "completed"
        if event.get("usage") is not None:
            state.final_usage = event["usage"]
    elif type_ == "error":
        state.finished_reason = event.get("finished_reason") or "error"


def _find_call(tool_calls: list, call_id: str | None) -> dict | None:
    if not call_id:
        return None
    for item in tool_calls:
        if item.get("id") == call_id:
            return item
    return None


def reduce_events(events: Iterable[dict]) -> dict:
    """把一段事件序列还原成消息字段（纯函数，不读执行器状态）。

    返回的 tool_calls 里 result 是事件口径（展示截断后的），status 是运行态；
    落库那份的 result 更长，见模块开头的说明。"""
    state = StreamState()
    for event in events:
        if event.get("type") in _NON_MESSAGE_EVENTS:
            continue
        apply_event(state, event)
    return {
        "content": state.content,
        "tool_calls": state.tool_calls,
        "citations": state.citations,
        "usage": state.usage(),
        "finished_reason": state.finished_reason,
    }


def tag_events(events: Iterable[dict], reply_id: str) -> Iterator[dict]:
    """给一段已有的事件序列补 seq / reply_id（回放、测试与将来从存储重放时用）。"""
    stream = EventStream(reply_id)
    for event in events:
        payload = {k: v for k, v in event.items() if k not in ("type", "reply_id", "seq")}
        yield stream.emit(event["type"], **payload)
