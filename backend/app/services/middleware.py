"""对话中间件：把轮数守卫、闸门、trace 这些"围着模型循环转"的逻辑收进一层（docs/16 P1）。

落点不是照搬 AgentScope 的六钩子，而是按 langgraph 1.2.11 实际能给的位置定的
（2026-10-26 用脚本实测，见 docs/16 §4.3）：

- `pre_model_hook` / `post_model_hook` 是**图节点**，不是包装器：pre 在 agent 之前、
  post 在 agent 之后，且 `tools → pre_model_hook → agent`，所以它们**每一轮 ReAct 都会跑**
  （首轮、以及每次工具执行完回到模型之前）
- 节点返回值按 state 的 reducer 合并，返回 {} 表示"这一轮不改状态"；抛异常会让节点失败、
  整个图失败——现有轮数守卫就是靠这个把运行记录置 failed
- 两个 hook 只支持同步函数（我们不需要异步；workflow 侧另有 asyncio.run 的桥接）

中间件只实现自己关心的点，装配时跳过没实现的方法，不产生调用开销。
"""
import json
import logging
from collections.abc import Callable, Iterable
from typing import Any

from langchain_core.messages import AIMessage

from app.services import chat_trace
from app.services.chat_events import StreamState

logger = logging.getLogger(__name__)


class ToolRoundsExceeded(Exception):
    """本轮工具调用超过 TOOL_CALL_MAX_ROUNDS。文案是给用户看的，原样下发。

    不放在 chat_runner 里：它是轮数守卫的产物，守卫搬进中间件后异常也跟着搬，
    chat_runner 只负责把它翻译成 finished_reason（exceed_max_iters）并置运行记录 failed。
    """

    def __init__(self, max_rounds: int):
        self.max_rounds = max_rounds
        super().__init__(f"超过最大工具调用轮数（{max_rounds}），已停止")


class ChatMiddleware:
    """中间件的可选接口。子类只实现需要的几个方法，其余保持 None。

    - post_model_hook() → 返回交给 create_react_agent 的节点函数（模型返回后、工具执行前）
    - pre_model_hook()  → 同上（模型调用前，每轮都会跑）
    - on_event(event)   → 观察者，收到执行器产出的每个事件，不允许改变它
    """

    def post_model_hook(self) -> Callable[[Any], dict] | None:
        return None

    def pre_model_hook(self) -> Callable[[Any], dict] | None:
        return None

    def on_system_prompt(self, prompt: str) -> str:
        return prompt

    def on_event(self, event: dict) -> None:
        return None


class RoundGuardMiddleware(ChatMiddleware):
    """轮数守卫：模型每次返回后数本轮已请求工具的次数，超过上限直接抛错。

    不能只靠 recursion_limit：预置 react 智能体在剩余步数不足时会自己回一句英文
    "Sorry, need more steps..." 正常结束，上层会把它当成功回答下发
    （langgraph 1.2.11 chat_agent_executor._are_more_steps_needed）。
    历史消息只有文本（chat_service._history_to_messages），state 里带 tool_calls 的 AIMessage
    都是本轮产生的，所以直接数它们即可。
    """

    def __init__(self, max_rounds: int):
        self.max_rounds = max_rounds

    def post_model_hook(self) -> Callable[[Any], dict]:
        def guard(state) -> dict:
            rounds = sum(1 for m in state["messages"] if isinstance(m, AIMessage) and m.tool_calls)
            if rounds > self.max_rounds:
                raise ToolRoundsExceeded(self.max_rounds)
            return {}

        return guard


def chain_hooks(middlewares: Iterable[ChatMiddleware | None], hook_name: str) -> Callable[[Any], dict] | None:
    """把多个中间件同一个位置的回调合成一个图节点；一个都没有时返回 None（不建节点）。

    合并规则：依次调用，把各自的返回值 update 成一个 dict。返回 {} 的中间件等于没说话，
    后一个看到的 state 仍是本轮开始时的 state（不把前一个的返回值提前喂给后一个）——
    目前没有需要串联的中间件，保持简单；将来真有需要再改成"逐个 apply 到 state 副本"。
    """
    hooks = []
    for middleware in middlewares:
        if middleware is None:
            continue
        hook = getattr(middleware, hook_name, None)
        if hook is None:
            continue
        fn = hook()
        if fn is not None:
            hooks.append(fn)
    if not hooks:
        return None

    def run(state) -> dict:
        updates: dict = {}
        for fn in hooks:
            part = fn(state)
            if part:
                updates.update(part)
        return updates

    return run


def apply_system_prompt(middlewares: Iterable[ChatMiddleware | None], prompt: str) -> str:
    """按装配顺序依次变换系统提示词（前一个的输出是后一个的输入）。"""
    for middleware in middlewares:
        if middleware is None:
            continue
        prompt = middleware.on_system_prompt(prompt)
    return prompt


def notify_event(middlewares: Iterable[ChatMiddleware | None], event: dict) -> None:
    """把事件分发给观察者（trace 用）。观察者异常只记日志，不能因为它打断对话。"""
    for middleware in middlewares:
        if middleware is None:
            continue
        try:
            middleware.on_event(event)
        except Exception:
            logger.exception("中间件处理事件失败：type=%s", event.get("type"))


class TraceMiddleware(ChatMiddleware):
    """调试调用链：把每次模型调用、每次工具执行记成 TraceStep（docs/15 3.4，FR-041）。

    模型调用以分块的 id 区分：第一个分块到达时开始、最后一个分块到达时结束；工具从模型调用
    结束时开始计时（工具节点跑完才一起返回，耗时是整个工具节点的）。

    **为什么还是显式三个方法，而不是纯 on_event 观察者**：llm 步骤要按"模型调用 id"归组
    chunk，并读那次调用的 usage——这两样只存在于 chunk 层（AIMessageChunk.id /
    usage_metadata），事件里没有。只凭事件顺序确实能推断出步骤边界，但 usage 会丢，
    调试面板的 token 就空掉了（回归）。等事件契约补上 call_id 与 usage 再改成观察者；
    在那之前，把逻辑搬进类里已经达到"不散在 chat_runner"的目的。
    """

    def __init__(self, model):
        self.model = model
        self.call: dict | None = None
        self.next_clock = chat_trace.Clock()
        self.tool_clock: chat_trace.Clock | None = None

    def on_chunk(self, call_id: str, text: str, tool_names: list[str]) -> None:
        if self.call is None or self.call["id"] != call_id:
            self.call = {"id": call_id, "clock": self.next_clock, "chars": 0, "tools": [], "first_token_ms": None}
        call = self.call
        if text and call["first_token_ms"] is None:
            call["first_token_ms"] = call["clock"].elapsed_ms()
        call["chars"] += len(text)
        call["tools"].extend(n for n in tool_names if n)
        call["clock"].stop()

    def close_call(self, state: StreamState) -> dict | None:
        call, self.call = self.call, None
        if call is None:
            return None
        self.tool_clock = call["clock"].successor()
        self.next_clock = chat_trace.Clock()
        return chat_trace.make_step("llm", self.model.name, call["clock"],
                                    output={"content_chars": call["chars"], "tool_calls": call["tools"]},
                                    meta={"model_id": self.model.id, "first_token_ms": call["first_token_ms"],
                                          "usage": state.usage_by_call.get(call["id"], {})})

    def tool_step(self, name: str, args, result: str) -> dict:
        try:
            parsed = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            parsed = None  # 工具返回的不是 JSON（纯文本结果，或被截断），按成功记
        failed = isinstance(parsed, dict) and "error" in parsed  # 执行器失败时返回 {"error": ...}，不抛异常
        clock = (self.tool_clock or chat_trace.Clock()).stop()
        self.next_clock = chat_trace.Clock()  # 下一次模型调用从工具结果回来时开始
        return chat_trace.make_step("tool", name, clock, input=args, output=result,
                                    status="error" if failed else "success")
