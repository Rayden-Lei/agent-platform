"""对外 HTTP 客户端的统一构造：回环地址不走代理。

开发机常设 HTTP_PROXY / HTTPS_PROXY 且没配 NO_PROXY，httpx / OpenAI SDK 默认信任环境变量，
访问 127.0.0.1 上的本地模型服务（oMLX 等）会被代理拦成 502。这里按目标地址决定是否信任代理环境：
回环地址一律直连，其余保持默认（生产环境通常没有代理变量，行为不变）。

**macOS 特别注意**：系统代理（Clash 等）即使没有导出 HTTP_PROXY 环境变量，urllib 也会读系统配置
返回代理（实测 getproxies() 给出 127.0.0.1:7890），而 httpx / httpx2 默认 trust_env=True 就会用上它。
所以"命令行里没有 proxy 变量"不等于"不会被代理"，这条判断必须按目标地址做，不能靠环境变量有没有值。

两份 httpx 并存：业务代码用 httpx，MCP SDK（mcp 2.x）用 httpx2，两者是不同的包、类型不通用。
下面的 *2 系列专供 MCP，别混用。
"""
from urllib.parse import urlparse

import httpx
import httpx2

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


# ---------- httpx2（MCP SDK 用的那一份） ----------

def async_client2(url: str | None, timeout) -> "httpx2.AsyncClient":
    """httpx2 的异步客户端，代理判定与上面同一口径。

    为什么必须有它：MCP 的 sse_client / streamable_http_client 默认用 SDK 自己的
    create_mcp_http_client()，那个工厂**不接受 trust_env**，于是 macOS 上配了系统代理时
    连 127.0.0.1 的 MCP 服务器会走代理、被拦成 502（表现为「连不上」但地址完全正确）。
    实测：本机 Clash 未导出任何 proxy 环境变量，httpx2 仍从系统配置读到 127.0.0.1:7890。
    """
    return httpx2.AsyncClient(timeout=timeout, trust_env=trust_env_for(url))


def mcp_http_client_factory(url: str | None):
    """给 sse_client 的 httpx_client_factory：签名必须与 SDK 的 McpHttpClientFactory 一致。

    单独做一层而不是直接传 async_client2：SDK 调用时会把 headers / timeout / auth 一起传进来，
    这里要原样转交，只把 trust_env 换成按目标地址算出来的值。
    """
    def _factory(headers=None, timeout=None, auth=None) -> "httpx2.AsyncClient":
        return httpx2.AsyncClient(timeout=timeout, headers=headers, auth=auth, trust_env=trust_env_for(url))
    return _factory
