"""模型网关：把数据库中的 ModelConfig 统一转成 LangChain ChatModel（OpenAI 兼容协议）。

集中处理 API Key 解密、base_url 归一化、流式开关与 default_params 映射，
上层（对话、工作流 agent 节点）只面对 ChatOpenAI 实例。
"""
from langchain_openai import ChatOpenAI

from app.config import settings
from app.core.security import decrypt_secret
from app.db.models import ModelConfig


def build_llm(model: ModelConfig):
    """根据数据库模型配置构建 LangChain ChatModel（OpenAI 兼容协议）。

    返回的实例默认开启 streaming（对话接口依赖流式输出）；
    default_params 中显式配置的采样参数（temperature/max_tokens/top_p）透传，未配置的用模型默认值。
    """
    params = model.default_params or {}
    kwargs = dict(
        model=model.model_name,
        api_key=decrypt_secret(model.api_key_enc),  # 库里存的是加密后的 Key，构建时解密
        base_url=model.api_base.rstrip("/"),  # 兼容配置里末尾带斜杠的 base_url
        timeout=settings.MODEL_HTTP_TIMEOUT,
        streaming=True,
        stream_usage=True,
    )
    if params.get("temperature") is not None:
        kwargs["temperature"] = params["temperature"]
    if params.get("max_tokens"):
        kwargs["max_tokens"] = params["max_tokens"]
    if params.get("top_p") is not None:
        kwargs["top_p"] = params["top_p"]
    return ChatOpenAI(**kwargs)
