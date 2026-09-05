"""入口治理基础（`12-差距补齐开发计划.md` 1.1）：IP 黑名单、客户端 IP 解析、CORS 白名单、审计来源 IP、配置校验。"""
import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.core.request_context import resolve_client_ip
from app.db.models import AuditLog
from app.db.session import SessionLocal

DENIED_NET = "10.9.0.0/16"
DENIED_IP = "10.9.1.7"
ALLOWED_IP = "10.10.0.1"
LOGIN = {"username": "admin", "password": "admin123"}


def test_denylist_blocks_login_but_not_health(monkeypatch, client_from):
    monkeypatch.setattr(settings, "IP_DENYLIST", DENIED_NET)
    c = client_from(DENIED_IP)
    r = c.post("/api/v1/auth/login", json=LOGIN)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "来源 IP 被拒绝"
    assert r.json()["trace_id"] == r.headers["x-request-id"]
    assert c.get("/health").status_code == 200


def test_denylist_403_carries_cors_headers(monkeypatch, client_from):
    """黑名单中间件在 CORS 内层：浏览器端拿到的是可读的 403，不是"网络错误"。"""
    monkeypatch.setattr(settings, "IP_DENYLIST", DENIED_NET)
    origin = settings.cors_origins[0]
    r = client_from(DENIED_IP).post("/api/v1/auth/login", json=LOGIN, headers={"Origin": origin})
    assert r.status_code == 403, r.text
    assert r.headers.get("access-control-allow-origin") == origin


def test_ip_outside_denylist_passes(monkeypatch, client_from):
    monkeypatch.setattr(settings, "IP_DENYLIST", DENIED_NET)
    r = client_from(ALLOWED_IP).post("/api/v1/auth/login", json=LOGIN)
    assert r.status_code == 200, r.text


def test_spoofed_forwarded_headers_ignored_without_trusted_proxy(monkeypatch, client_from):
    """默认不信任转发头：直连方伪造 X-Forwarded-For / X-Real-IP 不能改变来源判定。"""
    monkeypatch.setattr(settings, "IP_DENYLIST", DENIED_NET)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_ENABLED", False)
    r = client_from(ALLOWED_IP).post(
        "/api/v1/auth/login", json=LOGIN, headers={"X-Forwarded-For": DENIED_IP, "X-Real-IP": DENIED_IP},
    )
    assert r.status_code == 200, r.text


def test_trusted_proxy_uses_forwarded_headers(monkeypatch, client_from):
    monkeypatch.setattr(settings, "IP_DENYLIST", DENIED_NET)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_ENABLED", True)
    r = client_from("172.16.0.2").post(
        "/api/v1/auth/login", json=LOGIN, headers={"X-Forwarded-For": f"{DENIED_IP}, 172.16.0.2"},
    )
    assert r.status_code == 403, r.text


def _scope(headers: dict, client=("172.16.0.2", 1)) -> dict:
    return {"type": "http", "client": client, "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}


@pytest.mark.parametrize("headers,expected", [
    ({"X-Real-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8, 9.9.9.9"}, "1.2.3.4"),  # X-Real-IP 优先
    ({"X-Forwarded-For": "5.6.7.8, 9.9.9.9"}, "5.6.7.8"),                           # 其次取 XFF 首项
    ({"X-Real-IP": "not-an-ip"}, "172.16.0.2"),                                     # 非法值回退到对端
    ({"X-Forwarded-For": "x\ny, 5.6.7.8"}, "172.16.0.2"),                           # 首项非法不取后项，回退对端
    ({}, "172.16.0.2"),
])
def test_resolve_client_ip_with_trusted_proxy(monkeypatch, headers, expected):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_ENABLED", True)
    assert resolve_client_ip(_scope(headers)) == expected


def test_resolve_client_ip_without_trusted_proxy_ignores_headers(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_ENABLED", False)
    assert resolve_client_ip(_scope({"X-Real-IP": "1.2.3.4"})) == "172.16.0.2"


def test_audit_log_records_client_ip(client_from):
    """审计的 ip 列由请求上下文自动填充，调用点不必逐个传。"""
    r = client_from("10.10.0.9").post("/api/v1/auth/login", json=LOGIN)
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        row = (
            db.query(AuditLog)
            .filter(AuditLog.action == "login", AuditLog.username == "admin")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None
        assert row.ip == "10.10.0.9"
    finally:
        db.close()


def test_cors_whitelist_rejects_unknown_origin(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_cors_whitelist_allows_configured_origin(client):
    origin = settings.cors_origins[0]
    r = client.get("/health", headers={"Origin": origin})
    assert r.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize("field,value", [
    ("IP_DENYLIST", "10.0.0.0/33"),
    ("IP_DENYLIST", "abc"),
    ("CORS_ORIGINS", "localhost:18056"),          # 缺 scheme
    ("CORS_ORIGINS", "http://localhost:18056/"),  # 末尾斜杠永远匹配不上浏览器的 Origin
])
def test_invalid_gateway_config_fails_fast(field, value):
    """配置非法要在启动时报错退出，而不是运行时静默不拦。"""
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_gateway_config_parsing():
    s = Settings(IP_DENYLIST=" 10.0.0.0/8 , 192.168.1.1 ", CORS_ORIGINS="http://a.test,https://b.test:8443")
    assert s.ip_denylist == ["10.0.0.0/8", "192.168.1.1"]
    assert s.cors_origins == ["http://a.test", "https://b.test:8443"]
