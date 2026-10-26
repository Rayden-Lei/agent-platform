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
    """一轮执行中累积的结果，也是落库的真相。

    usage_by_call 按模型调用分开记再相加：一轮里有工具调用时模型会被调多次，2026-09-29 前
    每来一次用量就整体覆盖，只剩最后一次调用的 token，前几次的用量与成本都丢了。
    final_usage 是 done 事件里那份汇总（重放时只有它可用），不为空时优先返回，保证
    "实时跑出来的用量"与"从事件重放出来的用量"永远相等。
    finished_reason 只在 done / error 事件上出现：completed / interrupted / exceed_max_iters / error；
    为空表示这一轮还没收尾（例如客户端中途断开）。
    """

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
    """事件信封：给每条事件补 seq 与 reply_id，**不做任何累积**。

    累积必须由调用方显式 `apply_event(state, event)`。漏掉不会报错，只会让"事件重建"少一段内容，
    属于静默失效，所以生产路径里 emit 与 apply_event 总是相邻两行（见 chat_runner._agent_events）。
    """

    reply_id: str
    seq: int = 0

    def emit(self, type_: str, **payload) -> dict:
        event = {"type": type_, "reply_id": self.reply_id, "seq": self.seq, **payload}
        self.seq += 1
        return event


def apply_event(state: StreamState, event: dict, *, stored_result: str | None = None) -> None:
    """把一个事件累积进消息状态。实时产出与事后重放共用这一份，避免两条路径各写一套规则。

    各分支的累积规则与注意事项：
    - delta：拼接正文。事件是逐 token 的，落库只存拼好的整段，不存事件本身（一轮几百条，体积不划算）。
    - citations：整段替换。一次检索给的是完整列表，不存在增量。
    - tool_call：按 id 去重后追加，status 先记 running；同 id 再来时只更新 name / args。
      LangChain 可能先给完整 chunk（tool_calls）再给 ToolMessage 分支拼出来的参数，两次都建条目
      就是两张工具卡片；后到的参数更完整，所以覆盖而不是忽略。
    - tool_result：按 tool_call_id 回填 status 与 result；找不到对应 tool_call 时补一条只有结果的记录。
      工具结果先于调用事件到达、或调用事件因去重被跳过时，宁可少 name / args，也不能把结果丢掉。
    - done / error：只记终态。usage 只出现在 done 上（事件里没有逐次用量），写进 final_usage
      让 StreamState.usage() 优先返回它，重放与实时才是同一个数。
    - prompt / trace：调试专用，不属于消息内容，落到这里直接忽略。

    stored_result：实时路径传落库口径的工具结果（TOOL_RESULT_STORE_CHARS），不传时用事件里的
    展示口径（TOOL_RESULT_PREVIEW_CHARS）。只有实时路径能拿到全文——重放只有事件里那份，
    这是"事件可重建展示视图、全文以落库为准"的边界（见模块开头）。
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
    elif type_ == "llm_usage":
        # 一次模型调用的用量（2026-10-26 起）。写进 usage_by_call 后，重放能在没有 done 事件时
        # 也能算出本轮 token；有 done 时仍以 done 的汇总为准（usage() 里 final_usage 优先）。
        state.usage_by_call[event.get("call_id")] = event.get("usage") or {}
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
    """给一段已有的事件序列补 seq / reply_id（回放、测试与将来从存储重放时用）。

    返回的是生成器，只能遍历一次：需要"先断言 seq、再拿去重建"时先 list() 存下来，
    否则第二次循环拿到的是空序列（测试里踩过，表现是重建出空消息而不是报错）。
    """
    stream = EventStream(reply_id)
    for event in events:
        payload = {k: v for k, v in event.items() if k not in ("type", "reply_id", "seq")}
        yield stream.emit(event["type"], **payload)
