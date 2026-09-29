"""用例共用的模型桩：对话执行器、发布语义等用例都要"真走一遍对话链路、但不发网络请求"。

用法：use_llm(monkeypatch, AnswerModel(messages=iter(["回答"]))) 之后调对话接口；
把 chat_service.build_chat_context 换成返回桩模型的版本，检索、工具声明都不碰外部服务。
"""
import uuid
from types import SimpleNamespace

from langchain_core.language_models.chat_models import BaseChatModel, generate_from_stream
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.services import chat_service
from app.tools.langchain_tools import build_tools

# 熔断器按模型 id 计数：桩用负数 id，碰不到真实模型的熔断状态
FAKE_MODEL = SimpleNamespace(id=-20260925, name="pytest-fake-model")
# 导入时记住真正的实现：同一用例里多次 use_llm 时，模块属性已是上一次换进去的桩，不能再从那里取
_REAL_BUILD_CHAT_CONTEXT = chat_service.build_chat_context


class AnswerModel(GenericFakeChatModel):
    """流式吐出固定回答的桩；react 智能体会先 bind_tools，桩直接返回自己。"""

    def bind_tools(self, tools, **kwargs):
        return self


class ToolLoopModel(BaseChatModel):
    """每次都要求再调一次工具的桩。只实现非流式：流式桩会把 tool_calls 丢掉，react 智能体就不会进工具循环。"""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = AIMessage(content="", tool_calls=[{"name": "current_time", "args": {}, "id": "call_" + uuid.uuid4().hex[:8]}])
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "pytest-tool-loop"


class ScriptedModel(BaseChatModel):
    """按脚本逐次回答的流式桩：第 n 次调用取 script[n]，("tool", 工具名) 要求调一次无参工具，("text", 文本) 直接回答。
    每次调用都带用量（输入 10×n、输出 2），用来断言一轮里多次模型调用的用量要相加。
    实现 _stream 而不是只实现 _generate：langgraph 以 messages 模式流式时走它，工具参数才会以分块（tool_call_chunks）到达。"""

    script: list
    calls: int = 0

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        kind, value = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        usage = {"input_tokens": 10 * self.calls, "output_tokens": 2, "total_tokens": 10 * self.calls + 2}
        if kind == "tool":
            chunk = AIMessageChunk(content="", usage_metadata=usage,
                                   tool_call_chunks=[{"name": value, "args": "{}", "id": "call_" + uuid.uuid4().hex[:8], "index": 0}])
        else:
            chunk = AIMessageChunk(content=value, usage_metadata=usage)
        yield ChatGenerationChunk(message=chunk)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return generate_from_stream(self._stream(messages, stop, run_manager, **kwargs))

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "pytest-scripted"


def use_llm(monkeypatch, llm, captured: list | None = None) -> None:
    """对话改用桩模型。captured 传列表时记下每次构建上下文用的系统提示词，用来断言"回答按哪份配置"。"""

    def _build(db, agent_id, message_text, conversation_id, role=None, **kwargs):
        if captured is not None:
            captured.append(_REAL_BUILD_CHAT_CONTEXT(db, agent_id, message_text, conversation_id, role=role, **kwargs).system_prompt)
        return chat_service.ChatContext(model=FAKE_MODEL, llm=llm, tools=build_tools([]), system_prompt="你是测试助手",
                                        citations=[], history_messages=[HumanMessage(content=message_text)])

    monkeypatch.setattr(chat_service, "build_chat_context", _build)
