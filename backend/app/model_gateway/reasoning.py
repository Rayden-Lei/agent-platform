"""把第三方厂商的思维链字段从 SSE 里救回来。

langchain-openai 1.6.0 起，官方文档明确写了：

    ChatOpenAI targets official OpenAI API specifications only. Non-standard
    response fields added by third-party providers (e.g., `reasoning_content`,
    `reasoning_details`) are **not** extracted or preserved.

也就是说上游（DeepSeek 系、OpenRouter、vLLM 等）在 delta 里给的 `reasoning_content`
被 `_convert_delta_to_message_chunk` 直接丢掉，`additional_kwargs` 永远是空字典。
后端的 reasoning 事件因此一条都发不出来，前端"思考过程"永远是空的——
2026-11-05 使用者反馈"接的 deepseek v4.1 flash 不显示思考"就是这个原因。

官方给的替代方案是换 `ChatDeepSeek` / `ChatOpenRouter` 这类厂商专用包，但本项目是
"一套 OpenAI 兼容协议对接任意上游"（模型配置里 base_url 可换），不能按厂商分叉；
所以这里用子类接管 `_convert_chunk_to_generation_chunk`：先让父类照常转换，
再把被丢掉的推理字段补回 `additional_kwargs`。上游换人、LangChain 以后自己支持了，
这段就删掉。
"""
from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

# 各家的思维链字段名：DeepSeek 系用 reasoning_content，部分兼容端点用 reasoning / thinking。
# 顺序即优先级，只取第一个非空的。
REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")


class ReasoningChatOpenAI(ChatOpenAI):
    """保留上游 delta 里思维链字段的 ChatOpenAI。"""

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None:
            return None
        # beta.chat.completions.stream 的帧结构多一层 chunk，与父类取 choices 的口径保持一致
        choices = chunk.get("choices") or (chunk.get("chunk") or {}).get("choices") or []
        if not choices:
            return generation_chunk
        delta = choices[0].get("delta") or {}
        reasoning: Any = next((delta.get(k) for k in REASONING_KEYS if delta.get(k)), "")
        message = generation_chunk.message
        if reasoning and isinstance(reasoning, str) and isinstance(message, AIMessageChunk):
            # 复制而不是原地改：同一份 additional_kwargs 可能被父类复用，原地改会串到别的 chunk
            message.additional_kwargs = {**message.additional_kwargs, "reasoning_content": reasoning}
        return generation_chunk
