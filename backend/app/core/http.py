"""对外 HTTP 客户端的统一构造：回环地址不走代理。

开发机常设 HTTP_PROXY / HTTPS_PROXY 且没配 NO_PROXY，httpx / OpenAI SDK 默认信任环境变量，
访问 127.0.0.1 上的本地模型服务（oMLX 等）会被代理拦成 502。这里按目标地址决定是否信任代理环境：
回环地址一律直连，其余保持默认（生产环境通常没有代理变量，行为不变）。
"""
from urllib.parse import urlparse

import httpx

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def is_loopback(url: str | None) -> bool:
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in LOOPBACK_HOSTS


def trust_env_for(url: str | None) -> bool:
    """回环地址不信任代理环境变量，其余信任。"""
    return not is_loopback(url)


def sync_client(url: str | None, timeout: float | None) -> httpx.Client:
    return httpx.Client(timeout=timeout, trust_env=trust_env_for(url))


def async_client(url: str | None, timeout: float | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, trust_env=trust_env_for(url))
