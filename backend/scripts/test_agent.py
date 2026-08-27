import asyncio
import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent


async def main():
    # 1. 纯文本回答
    print("=== 场景1：纯文本流式 ===")
    llm = GenericFakeChatModel(messages=iter(["你好，我是助手。"]))
    agent = create_react_agent(llm, [], prompt="你是助手")
    async for chunk, meta in agent.astream({"messages": [HumanMessage(content="hi")]}, stream_mode="messages"):
        print("type=", type(chunk).__name__, "| node=", meta.get("langgraph_node"), "| content=", repr(chunk.content))

    # 2. 工具调用场景
    print()
    print("=== 场景2：工具调用 ===")
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "calculator", "args": {"expression": "2+3"}, "id": "call_1", "type": "tool_call"}],
    )
    llm2 = GenericFakeChatModel(messages=iter([tool_call_msg, "结果是 5。"]))
    from langchain_core.tools import tool

    @tool
    def calculator(expression: str) -> str:
        """计算表达式"""
        return str(eval(expression))

    agent2 = create_react_agent(llm2, [calculator], prompt="你是助手")
    async for chunk, meta in agent2.astream({"messages": [HumanMessage(content="算一下 2+3")]}, stream_mode="messages"):
        print("type=", type(chunk).__name__, "| node=", meta.get("langgraph_node"), "| content=", repr(chunk.content), "| tool_calls=", getattr(chunk, "tool_calls", None))


asyncio.run(main())
