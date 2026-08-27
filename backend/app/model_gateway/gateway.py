from langchain_openai import ChatOpenAI

from app.config import settings
from app.core.security import decrypt_secret
from app.db.models import ModelConfig


def build_llm(model: ModelConfig):
    """根据数据库模型配置构建 LangChain ChatModel（OpenAI 兼容协议）。"""
    params = model.default_params or {}
    kwargs = dict(
        model=model.model_name,
        api_key=decrypt_secret(model.api_key_enc),
        base_url=model.api_base.rstrip("/"),
        timeout=settings.MODEL_HTTP_TIMEOUT,
        streaming=True,
    )
    if params.get("temperature") is not None:
        kwargs["temperature"] = params["temperature"]
    if params.get("max_tokens"):
        kwargs["max_tokens"] = params["max_tokens"]
    if params.get("top_p") is not None:
        kwargs["top_p"] = params["top_p"]
    return ChatOpenAI(**kwargs)
