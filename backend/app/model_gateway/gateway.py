"""模型网关：把数据库中的 ModelConfig 统一转成 LangChain ChatModel（OpenAI 兼容协议），并给调用套上熔断。

集中处理 API Key 解密、base_url 归一化、流式开关与 default_params 映射，
上层（对话、工作流 agent 节点、连通测试）只面对 ChatOpenAI 实例与三个 guarded_* 包装。
"""
from langchain_openai import ChatOpenAI

from app.config import settings
from app.core.security import decrypt_secret
from app.db.models import ModelConfig
from app.model_gateway import breaker


def build_llm(model: ModelConfig):
    """根据数据库模型配置构建 LangChain ChatModel（OpenAI 兼容协议）。

    返回的实例默认开启 streaming（对话接口依赖流式输出）；
    default_params 中显式配置的采样参数（temperature/max_tokens/top_p）透传，未配置的用模型默认值。
    max_retries 显式传 MODEL_MAX_RETRIES（默认 0）：不设的话 SDK 默认重试 2 次，超时类故障一次"失败"
    实际要等 3 × MODEL_HTTP_TIMEOUT；故障处理统一交给熔断器。
    """
    params = model.default_params or {}
    kwargs = dict(
        model=model.model_name,
        api_key=decrypt_secret(model.api_key_enc),  # 库里存的是加密后的 Key，构建时解密
        base_url=model.api_base.rstrip("/"),  # 兼容配置里末尾带斜杠的 base_url
        timeout=settings.MODEL_HTTP_TIMEOUT,
        max_retries=settings.MODEL_MAX_RETRIES,
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


def guarded_invoke(model: ModelConfig, llm, input_value):
    """同步调用 + 熔断：打开期直接抛 BizError(503) 不请求上游；结果按熔断器规则记录。"""
    breaker.before_call(model.id, model.name)
    try:
        resp = llm.invoke(input_value)
    except Exception as e:
        breaker.record_failure(model.id, model.name, e)
        raise
    breaker.record_success(model.id, model.name)
    return resp


async def guarded_ainvoke(model: ModelConfig, llm, input_value, *, probe: bool = False):
    """异步调用 + 熔断。probe=True 跳过打开期判定（连通测试用作人工恢复手段），结果照常记录。"""
    if not probe:
        breaker.before_call(model.id, model.name)
    try:
        resp = await llm.ainvoke(input_value)
    except Exception as e:
        breaker.record_failure(model.id, model.name, e)
        raise
    breaker.record_success(model.id, model.name)
    return resp


async def guarded_astream(model: ModelConfig, stream):
    """包装异步流 + 熔断：拿到首个 chunk 视为成功；建立流之前的异常计失败；流中途断开不计数。"""
    breaker.before_call(model.id, model.name)
    first = True
    try:
        async for item in stream:
            if first:
                breaker.record_success(model.id, model.name)
                first = False
            yield item
    except Exception as e:
        if first:
            breaker.record_failure(model.id, model.name, e)
        raise
