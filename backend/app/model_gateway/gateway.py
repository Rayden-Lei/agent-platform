"""模型网关：把数据库中的 ModelConfig 统一转成 LangChain ChatModel（OpenAI 兼容协议），并给调用套上熔断。

集中处理 API Key 解密、base_url 归一化、流式开关与 default_params 映射，
上层（对话、工作流 agent 节点、连通测试）只面对 ChatOpenAI 实例与三个 guarded_* 包装。
"""
import threading
from collections import OrderedDict

from langchain_openai import ChatOpenAI

from app.config import settings
from app.core.http import async_client, sync_client
from app.core.security import decrypt_secret
from app.db.models import ModelConfig
from app.model_gateway import breaker


# 按 (模型 id, updated_at) 缓存 ChatOpenAI 实例：底层 httpx 连接池得以复用，省掉每次对话的 TLS 握手；
# 模型配置任何改动都会刷新 updated_at，自然换新实例。实例本身线程安全，流式状态是每次调用私有的。
_LLM_CACHE: "OrderedDict[tuple, ChatOpenAI]" = OrderedDict()
_LLM_CACHE_LOCK = threading.Lock()
_LLM_CACHE_MAX = 64


def build_llm(model: ModelConfig):
    """根据数据库模型配置构建 LangChain ChatModel（OpenAI 兼容协议），同一配置复用实例。

    返回的实例默认开启 streaming（对话接口依赖流式输出）；
    default_params 中显式配置的采样参数（temperature/max_tokens/top_p）透传，未配置的用模型默认值；
    thinking（disabled / enabled）以 extra_body 透传给 DeepSeek 类混合推理模型。
    max_retries 显式传 MODEL_MAX_RETRIES（默认 0）：不设的话 SDK 默认重试 2 次，超时类故障一次"失败"
    实际要等 3 × MODEL_HTTP_TIMEOUT；故障处理统一交给熔断器。
    """
    key = (model.id, str(model.updated_at), model.api_base, model.model_name)
    with _LLM_CACHE_LOCK:
        cached = _LLM_CACHE.get(key)
        if cached is not None:
            _LLM_CACHE.move_to_end(key)
            return cached
    llm = _new_llm(model)
    with _LLM_CACHE_LOCK:
        # 同一模型的旧配置实例直接淘汰，其余按 LRU 限量
        for old_key in [k for k in _LLM_CACHE if k[0] == model.id]:
            _LLM_CACHE.pop(old_key, None)
        _LLM_CACHE[key] = llm
        while len(_LLM_CACHE) > _LLM_CACHE_MAX:
            _LLM_CACHE.popitem(last=False)
    return llm


def reset_llm_cache() -> None:
    """测试用：清空实例缓存。"""
    with _LLM_CACHE_LOCK:
        _LLM_CACHE.clear()


def _new_llm(model: ModelConfig):
    params = model.default_params or {}
    kwargs = dict(
        model=model.model_name,
        api_key=decrypt_secret(model.api_key_enc),  # 库里存的是加密后的 Key，构建时解密
        base_url=model.api_base.rstrip("/"),  # 兼容配置里末尾带斜杠的 base_url
        timeout=settings.MODEL_HTTP_TIMEOUT,
        max_retries=settings.MODEL_MAX_RETRIES,
        streaming=True,
        stream_usage=True,
        # 回环地址（本机 oMLX 等）不走代理环境变量；远程厂商保持默认行为
        http_client=sync_client(model.api_base, settings.MODEL_HTTP_TIMEOUT),
        http_async_client=async_client(model.api_base, settings.MODEL_HTTP_TIMEOUT),
    )
    if params.get("temperature") is not None:
        kwargs["temperature"] = params["temperature"]
    if params.get("max_tokens"):
        kwargs["max_tokens"] = params["max_tokens"]
    if params.get("top_p") is not None:
        kwargs["top_p"] = params["top_p"]
    # 思考模式（DeepSeek 等混合推理模型）：关闭后首字节从 8 秒级降到 3 秒级；未设置时不发该字段，避免不认识的上游报 400
    if params.get("thinking") in ("disabled", "enabled"):
        kwargs["extra_body"] = {"thinking": {"type": params["thinking"]}}
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
