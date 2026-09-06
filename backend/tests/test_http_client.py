"""`core/http`：回环地址不走代理环境变量，远程地址照常信任环境（2026-09-06，本机 oMLX 被 HTTP_PROXY 拦成 502 的教训）。"""
from app.core import http as core_http


def test_loopback_urls_bypass_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.test:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:7890")
    for url in ("http://127.0.0.1:8000/v1", "http://localhost:8000/v1", "http://[::1]:8000/v1"):
        assert core_http.is_loopback(url) and core_http.trust_env_for(url) is False
        client = core_http.sync_client(url, 5)
        # httpx 在 trust_env=False 时不会装载环境代理
        assert not any(client._mounts.values()) or all(m is None for m in client._mounts.values())
        client.close()


def test_remote_urls_keep_env_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:7890")
    url = "https://api.example.com/v1"
    assert core_http.is_loopback(url) is False and core_http.trust_env_for(url) is True
    client = core_http.sync_client(url, 5)
    assert any(m is not None for m in client._mounts.values())  # 装载了代理传输
    client.close()


def test_empty_url_is_not_loopback():
    assert core_http.is_loopback(None) is False and core_http.is_loopback("") is False
