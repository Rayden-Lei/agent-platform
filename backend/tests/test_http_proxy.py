"""对外 HTTP 客户端的代理口径（2026-11-18 补）。

为什么要有这组用例：macOS 上 Clash 这类系统代理**即使没有导出任何 proxy 环境变量**，
urllib 也会读到系统配置并返回代理（实测 getproxies() 给出 127.0.0.1:7890），
而 httpx / httpx2 默认 trust_env=True 就会用上它。于是"连 127.0.0.1 上的服务"
会被代理劫持、拦成 502，报错文案却是"连不上"或"服务返回错误"—— 地址完全正确，
排查方向会被带偏到目标服务上（2026-11-18 就因此让两条 MCP 用例长期失败，
单跑时好时坏，取决于代理是否在跑）。

修法是按**目标地址**决定 trust_env，而不是看环境变量有没有值。这里钉住：
1. 回环地址一律不信任代理环境（直连）；
2. 非回环地址保持信任（生产通常没有代理变量，行为不变）；
3. MCP 用的 httpx2 与业务用的 httpx 是两份包，两边都要覆盖；
4. 给 SDK 的 httpx_client_factory 必须把 headers / timeout / auth 原样转交 ——
   少转一个就会让 MCP 的鉴权头或超时静默失效。
"""
from __future__ import annotations

import pytest

from app.core import http as http_util


# --------------------------------------------------------------------------- 地址判定

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/mcp",
    "http://localhost:11434/v1",
    "http://[::1]:9000/x",
    "http://0.0.0.0:5000/x",
])
def test_loopback_hosts_do_not_trust_proxy_env(url):
    """回环地址必须直连：这是"本机服务被系统代理劫持成 502"的唯一修法。"""
    assert http_util.is_loopback(url) is True
    assert http_util.trust_env_for(url) is False


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1",
    "https://github.com/owner/repo",
    "http://10.0.0.5:8080/x",
    "https://api.example.com/mcp",
])
def test_public_and_private_hosts_keep_trusting_proxy_env(url):
    """非回环地址保持默认行为：内网 IP 也可能需要经公司代理访问，不能一刀切直连。"""
    assert http_util.is_loopback(url) is False
    assert http_util.trust_env_for(url) is True


def test_missing_or_empty_url_is_not_loopback():
    """地址缺失时不当作回环：宁可按默认（信任环境变量）走，也不要意外直连。"""
    assert http_util.is_loopback(None) is False
    assert http_util.is_loopback("") is False


# --------------------------------------------------------------------------- 两份 httpx 都要覆盖

def test_sync_and_async_clients_apply_loopback_rule():
    """httpx（业务侧）两个构造都要按地址决定 trust_env。"""
    assert http_util.sync_client("http://127.0.0.1:1/x", 1).trust_env is False
    assert http_util.async_client("http://127.0.0.1:1/x", 1).trust_env is False
    assert http_util.sync_client("https://api.example.com/x", 1).trust_env is True
    assert http_util.async_client("https://api.example.com/x", 1).trust_env is True


def test_httpx2_clients_apply_loopback_rule():
    """httpx2（MCP SDK 用的那一份）同样要覆盖 —— 两份包类型不通用，只改一边等于没改。"""
    assert http_util.async_client2("http://127.0.0.1:1/mcp", 1).trust_env is False
    assert http_util.async_client2("https://mcp.example.com/mcp", 1).trust_env is True


def test_mcp_factory_passes_headers_timeout_and_auth_through():
    """给 SDK 的工厂必须原样转交参数：少转 headers 会让鉴权头失效，少转 timeout 会让长流被掐。"""
    import httpx2

    factory = http_util.mcp_http_client_factory("http://127.0.0.1:1/mcp")
    client = factory(headers={"Authorization": "Bearer x"}, timeout=httpx2.Timeout(5, read=5))
    assert client.headers["authorization"] == "Bearer x"
    assert client.trust_env is False
    # 超时对象要原样带上（httpx2 内部转成 Timeout，比较 read 值即可）
    assert client.timeout.read == 5


def test_mcp_factory_for_public_url_trusts_env():
    """公网 MCP 服务器保持信任代理环境（企业网络里常常只能经代理出去）。"""
    factory = http_util.mcp_http_client_factory("https://mcp.example.com/mcp")
    client = factory()
    assert client.trust_env is True
