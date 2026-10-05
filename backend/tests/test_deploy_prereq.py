"""对外部署前提（docs/15 PB-07，AC-029 ⑤ 与对外地址）：来源 IP 自检、PUBLIC_BASE_URL 的校验与下发。

代理层覆写 X-Real-IP（vite.config.ts / nginx.conf）与 frame-ancestors 响应头在托管层，用 vite preview 实测，不在这里。
"""
import pytest
from pydantic import ValidationError

from app.config import Settings, settings

STATUS = "/api/v1/system/status"


def _client_ip_degraded(body: dict) -> bool:
    return any(d["item"] == "client_ip" for d in body["degraded"])


def test_trusted_proxy_without_real_ip_header_is_degraded(client, auth_headers, monkeypatch):
    """开了 TRUSTED_PROXY_ENABLED 却没收到合法的 X-Real-IP：说明代理没有覆写来源，degraded 点名 client_ip。"""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_ENABLED", True)
    body = client.get(STATUS, headers=auth_headers).json()
    assert body["client_ip"]["ok"] is False and body["client_ip"]["real_ip_header"] is False
    assert _client_ip_degraded(body)
    forged = client.get(STATUS, headers={**auth_headers, "X-Real-IP": "not-an-ip"}).json()  # 不是合法 IP 当作没带
    assert _client_ip_degraded(forged)


def test_trusted_proxy_with_real_ip_header_is_not_degraded(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_ENABLED", True)
    body = client.get(STATUS, headers={**auth_headers, "X-Real-IP": "203.0.113.9"}).json()
    assert body["client_ip"] == {"trusted_proxy": True, "real_ip_header": True, "resolved": "203.0.113.9", "ok": True}
    assert not _client_ip_degraded(body)


def test_proxy_check_is_silent_when_proxy_is_not_trusted(client, auth_headers, monkeypatch):
    """开关没开时不判定：本机开发经代理访问时来源恒为回环地址，属预期，不能一直误报。"""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_ENABLED", False)
    body = client.get(STATUS, headers=auth_headers).json()
    assert body["client_ip"]["ok"] is True and body["client_ip"]["trusted_proxy"] is False
    assert not _client_ip_degraded(body)


def test_me_carries_public_base_url(client, auth_headers, monkeypatch):
    """对外地址经 /auth/me 下发（分享链接、API 示例用）；没配置是空串，前端用当前访问的地址。"""
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    assert client.get("/api/v1/auth/me", headers=auth_headers).json()["public_base_url"] == ""
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://agent.example.com")
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()
    assert me["public_base_url"] == "https://agent.example.com" and me["username"] and "must_change_password" in me


@pytest.mark.parametrize("raw,expected", [
    ("", ""),
    ("  ", ""),
    ("https://agent.example.com/", "https://agent.example.com"),
    ("http://10.0.0.5:4173", "http://10.0.0.5:4173"),
    ("https://example.com/agent/", "https://example.com/agent"),
])
def test_public_base_url_is_normalised(raw, expected):
    assert Settings(PUBLIC_BASE_URL=raw).PUBLIC_BASE_URL == expected


@pytest.mark.parametrize("raw", ["agent.example.com", "ftp://agent.example.com", "https://", "https://a.com/?x=1", "https://a.com/#top"])
def test_bad_public_base_url_fails_at_startup(raw):
    """配错启动即报错：不留到外部用户打不开分享链接才发现。"""
    with pytest.raises(ValidationError):
        Settings(PUBLIC_BASE_URL=raw)


def test_db_connections_use_tcp_keepalive():
    """连接池的连接带 TCP keepalive（2026-10-05 起）：经 NAT 连共享库时，闲置几分钟的连接会被中间设备悄悄回收，
    重连后旧连接留在库里成孤儿（库按 7200 秒的 keepalive 才回收），两小时攒了 70 多个、逼近 max_connections。
    当天的对照实验：闲置 6 分钟后，带 keepalive 的连接原样复用，不带的要 19 秒才发现已断并重连，旧连接留在库里。"""
    from app.db.session import engine

    with engine.connect() as conn:
        params = conn.connection.dbapi_connection.get_dsn_parameters()
    assert params.get("keepalives") == "1"
    assert int(params["keepalives_idle"]) <= 60  # 要比常见 NAT 的空闲回收时间短
