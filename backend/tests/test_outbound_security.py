"""工作流出站安全：HTTP 节点的 SSRF 防护，以及条件节点的表达式沙箱。

两条都是 2026-11-14 审计的发现：
- 条件节点原用 eval + __builtins__ 收窄，实测可逃逸执行任意命令（P0）；
- HTTP 节点完全没有出站闸门，可打云元数据 169.254.169.254（P1）。
"""
from __future__ import annotations

import pytest

from app.core import outbound
from app.workflow.safe_eval import ConditionSyntaxError, evaluate, validate_expression


# ===== 表达式沙箱 =====

def test_expression_cannot_escape_via_object_graph():
    """审计实测过的逃逸 payload 必须全部拒绝。

    改造前 eval(expr, {"__builtins__": {}}, ns) 挡不住子类遍历，整条 escape 能起子进程。
    """
    payloads = [
        "().__class__.__base__.__subclasses__()",
        "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'Popen'][0]",
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "input.items()",
        "9**9**9",
        "lambda: 1",
        "f'{input}'",
        "(y := 5)",
    ]
    env = {"input": {"a": 1}, "loop_index": 1}
    for expr in payloads:
        with pytest.raises(ConditionSyntaxError):
            evaluate(expr, env)


def test_expression_supports_normal_conditions():
    """正常条件表达式不受影响 —— 收紧安全不能把功能收没了。"""
    env = {"input": {"score": 85, "name": "abc"}, "loop_index": 2}
    assert evaluate("input['score'] > 60", env) is True
    assert evaluate("input['name'] == 'abc' and loop_index < 5", env) is True
    assert evaluate("len(input['name']) == 3", env) is True
    assert evaluate("not (loop_index > 10)", env) is True
    assert evaluate("'a' in input['name']", env) is True


def test_expression_division_by_zero_is_caught():
    """除零是笔误，不该让整个工作流运行抛异常。"""
    with pytest.raises(ConditionSyntaxError):
        evaluate("loop_index / 0 > 1", {"loop_index": 1})


def test_validate_expression_rejects_syntax_error():
    with pytest.raises(ConditionSyntaxError):
        validate_expression("input > ")
    with pytest.raises(ConditionSyntaxError):
        validate_expression("")


# ===== 出站白名单 =====

def test_private_addresses_are_blocked():
    """内网与云元数据地址一律拒绝（None 模式：只拦内网、放行公网）。"""
    for host in ("127.0.0.1", "169.254.169.254", "192.168.1.1", "10.0.0.1", "::1"):
        with pytest.raises(outbound.OutboundBlocked):
            outbound.check_host(host, None)


def test_public_host_passes_in_permissive_mode():
    """内置工具那种「公网可达但碰不到内网」的模式。"""
    outbound.check_host("example.com", None)  # 不抛错即通过


def test_empty_allowlist_denies_everything():
    """工具行 / 工作流节点那种严格模式：空名单 = 拒绝，不是「放行所有」。"""
    with pytest.raises(outbound.OutboundBlocked, match="没有配置允许访问的域名"):
        outbound.check_host("example.com", [])


def test_allowlist_wildcard_matching():
    assert outbound.pattern_matches("api.example.com", "*.example.com") is True
    assert outbound.pattern_matches("example.com", "*.example.com") is False  # 通配不吃裸域
    assert outbound.pattern_matches("example.com", "example.com") is True
    assert outbound.pattern_matches("evil.com", "*.example.com") is False


def test_allowlist_denies_host_outside_list():
    with pytest.raises(outbound.OutboundBlocked, match="不在白名单内"):
        outbound.check_host("evil.com", ["*.example.com"])


def _fake_dns(monkeypatch, mapping: dict[str, str]):
    """让 *.example.com 解析到公网 IP，测试不必依赖真实 DNS 与网络。"""
    import socket as _socket

    def _resolve(host, port, *args, **kwargs):
        ip = mapping.get(host)
        if ip is None:
            raise _socket.gaierror("mocked: unknown host")
        # getaddrinfo 的形状：(family, type, proto, canonname, sockaddr)
        family = _socket.AF_INET6 if ":" in ip else _socket.AF_INET
        return [(family, _socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(outbound, "_resolver", _resolve)


def test_redirect_to_private_address_is_blocked(monkeypatch):
    """302 到内网地址必须被拦 —— 这是 follow_redirects=True 的经典绕过。"""
    import httpx

    _fake_dns(monkeypatch, {
        "a.example.com": "93.184.216.34",
        "b.example.com": "93.184.216.35",
        "c.example.com": "93.184.216.36",
        "169.254.169.254": "169.254.169.254",
    })
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, **kwargs):
            calls["n"] += 1
            req = httpx.Request(method, url)
            # 前两跳合法，第三跳跳到云元数据
            target = {"https://a.example.com/x": "https://b.example.com/y",
                      "https://b.example.com/y": "https://c.example.com/z",
                      "https://c.example.com/z": "http://169.254.169.254/latest/meta-data/"}[url]
            return httpx.Response(302, headers={"location": target}, request=req)

    monkeypatch.setattr(outbound.httpx, "Client", _FakeClient)
    with pytest.raises(outbound.OutboundBlocked):
        outbound.request_with_checked_redirects(
            "https://a.example.com/x", allowed=["*.example.com"], timeout=1)
    assert calls["n"] == 3  # 第三跳的目标在发请求之前就被拦下了


def test_redirect_within_allowlist_is_followed(monkeypatch):
    """合法域名之间的重定向要正常跟过去，不能一律拒绝。"""
    import httpx

    _fake_dns(monkeypatch, {
        "a.example.com": "93.184.216.34",
        "b.example.com": "93.184.216.35",
    })

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, **kwargs):
            req = httpx.Request(method, url)
            if url.endswith("/x"):
                return httpx.Response(302, headers={"location": "https://b.example.com/y"}, request=req)
            return httpx.Response(200, text="ok", request=req)

    monkeypatch.setattr(outbound.httpx, "Client", _FakeClient)
    resp = outbound.request_with_checked_redirects(
        "https://a.example.com/x", allowed=["*.example.com"], timeout=1)
    assert resp.status_code == 200 and resp.text == "ok"


def test_http_node_without_allowlist_fails_cleanly():
    """未配白名单的 HTTP 节点应当失败并给出可读原因，而不是发出去。"""
    from app.workflow.engine import build_workflow

    graph = {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
            {"id": "h", "type": "http", "config": {"url": "https://example.com/api", "method": "GET"}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "h"}, {"from": "h", "to": "e"}],
    }
    g = build_workflow(graph)
    with pytest.raises(Exception) as exc:
        g.invoke({"input": "x", "steps": []}, {"configurable": {"thread_id": "pytest-http-ssrf"}})
    assert "域名" in str(exc.value) or "白名单" in str(exc.value)
