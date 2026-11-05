"""思维链（reasoning）提取：langchain-openai 1.6.0 起不再保留第三方厂商的 reasoning_content。

2026-11-05 使用者反馈"接的 deepseek v4.1 flash 不显示思考"。上游 SSE 里一直有
`reasoning_content`（原始请求验证过），是 ChatOpenAI 的
`_convert_delta_to_message_chunk` 把它丢掉了，官方文档写明这类非标准字段
"are not extracted or preserved"，建议换厂商专用包。本项目一套协议对接任意上游，
所以用 ReasoningChatOpenAI 子类把字段补回 additional_kwargs。

这里直接调用转换方法，不发网络请求。
"""
import pytest

from app.model_gateway.reasoning import ReasoningChatOpenAI
from langchain_core.messages import AIMessageChunk


def _llm():
    # 只用到转换方法，不建真实客户端：base_url / api_key 给占位值即可
    return ReasoningChatOpenAI(model="x", api_key="sk-test", base_url="http://upstream.test/v1")


def _chunk(delta: dict) -> dict:
    return {"choices": [{"delta": delta, "index": 0}]}


@pytest.mark.parametrize("field", ["reasoning_content", "reasoning", "thinking"])
def test_reasoning_delta_is_preserved(field):
    """DeepSeek 系的 reasoning_content，以及部分兼容端点用的 reasoning / thinking，都要留住。"""
    llm = _llm()
    out = llm._convert_chunk_to_generation_chunk(_chunk({"content": "", field: "思考中"}), AIMessageChunk, None)
    assert out is not None
    assert out.message.additional_kwargs["reasoning_content"] == "思考中"


def test_reasoning_does_not_overwrite_other_kwargs():
    """补 reasoning_content 时不能把父类已放的字段冲掉。"""
    llm = _llm()
    chunk = _chunk({"content": "正文", "reasoning_content": "想一下", "function_call": {"name": "f", "arguments": "{}"}})
    out = llm._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert out.message.additional_kwargs["reasoning_content"] == "想一下"
    assert out.message.additional_kwargs["function_call"]["name"] == "f"
    assert out.message.content == "正文"


def test_plain_delta_has_no_reasoning_key():
    """普通回答不该凭空多出一个 reasoning_content 键，否则前端会显示空的思考行。"""
    llm = _llm()
    out = llm._convert_chunk_to_generation_chunk(_chunk({"content": "你好"}), AIMessageChunk, None)
    assert out is not None
    assert "reasoning_content" not in out.message.additional_kwargs


def test_empty_choices_does_not_crash():
    """usage-only 帧（choices 为空）要原样返回，不能因为取 delta 下标越界。"""
    llm = _llm()
    out = llm._convert_chunk_to_generation_chunk({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}, AIMessageChunk, None)
    assert out is not None
