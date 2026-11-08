"""两层白名单的语义差异：内置 http_request 与工具行闸门对「空名单」的处理相反。

这不是矛盾，是两层不同的东西 —— 但这层区分以前没写清楚，容易被当成 bug 去"修"，
一修就把安全性改坏。用测试把当前语义固定下来，改之前先看这里。

- **工具行闸门**（`tools/permission.check`，管 type=http / mcp）：
  空名单 = **拒绝**。地址是管理员填的任意 URL，没白名单就无从判断目标是否可信。
- **内置 http_request**（`tools/general._host_allowed`，type=builtin）：
  空名单 = **只拦内网、放行公网**。它在 permission.check 里第 2 步就被 allow 掉了
  （内置工具没有"工具行地址"可查），所以自己管自己的出站安全：
  强制 DNS 解析后拦内网段，防止 `http://127.0.0.1` 换个域名绕过。

两者对空的处理相反，是因为默认值的安全性不同：内置工具"公网可达但碰不到内网"
已经是安全下限；工具行地址是任意 URL，没有白名单则完全没有约束。
"""
from __future__ import annotations

import pytest

from app.tools import general, permission
from app.tools.permission import ToolCallContext
from app.db.models import Tool


def _tool(**kw) -> Tool:
    return Tool(name=kw.get("name", "t"), description="d", type=kw.get("type", "http"),
                config=kw.get("config", {}), is_enabled=kw.get("is_enabled", True))


# --------------------------------------------------------------------------- 工具行闸门：空名单拒绝

def test_gate_denies_empty_user_allowlist_for_http_tool():
    """工具行（type=http）没配 allowed_hosts → 拒绝。地址是任意 URL，没有白名单则闸门不存在。"""
    t = _tool(type="http", config={"url": "https://api.example.com/x", "allowed_hosts": []})
    decision, reason = permission.check(ToolCallContext(tool=t, source="chat"))
    assert decision == "deny"
    assert "allowed_hosts" in reason


def test_gate_denies_empty_allowlist_for_mcp_tool():
    """MCP 工具同一口径：地址由管理员配，空名单拒绝。"""
    t = _tool(type="mcp", config={"url": "https://mcp.example.com/mcp", "allowed_hosts": []})
    decision, reason = permission.check(ToolCallContext(tool=t, source="chat"))
    assert decision == "deny"


def test_gate_allows_builtin_without_allowlist():
    """内置工具在第 2 步就放行：它没有"工具行地址"可查，闸门那套对它不适用。

    这是理解「两层语义为何相反」的关键 —— 内置 http_request 根本不经过下面那层白名单判定，
    所以它必须自己管出站安全。
    """
    t = _tool(type="builtin", config={})
    decision, reason = permission.check(ToolCallContext(tool=t, source="chat"))
    assert decision == "allow"


# --------------------------------------------------------------------------- 内置 http_request：空名单只拦内网

def test_builtin_empty_allowlist_allows_public_host(monkeypatch):
    """内置 http_request 空名单时放行公网 —— 让工具开箱可用。"""
    monkeypatch.setattr(general.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))])
    ok, reason = general._host_allowed("example.com", "")
    assert ok is True, reason


@pytest.mark.parametrize("private_ip", ["127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1", "169.254.1.1"])
def test_builtin_blocks_private_addresses_even_without_allowlist(monkeypatch, private_ip):
    """**空名单也必须拦内网**：否则 http://127.0.0.1:5432 就能从对话里打内网服务。

    这是内置工具的安全下限 —— 它比工具行那层"松"，但不是没有底线。
    """
    monkeypatch.setattr(general.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, None, (private_ip, 0))])
    ok, reason = general._host_allowed("evil.example.com", "")
    assert ok is False
    assert "内网" in reason


def test_builtin_blocks_when_domain_resolves_to_private(monkeypatch):
    """域名解析到内网 IP 同样拦：光看域名字面会被绕过。"""
    monkeypatch.setattr(general.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, None, ("192.168.0.7", 0))])
    ok, reason = general._host_allowed("totally-public-looking.com", "")
    assert ok is False
    assert "192.168.0.7" in reason


def test_builtin_allowlist_narrows_public_access(monkeypatch):
    """填了白名单就严格按白名单：公网域名不在名单里也要拒。"""
    monkeypatch.setattr(general.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))])
    ok, reason = general._host_allowed("other.com", "example.com")
    assert ok is False
    assert "白名单" in reason or "不在" in reason


def test_builtin_allowlist_supports_exact_and_suffix(monkeypatch):
    monkeypatch.setattr(general.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))])
    assert general._host_allowed("example.com", "example.com")[0] is True
    assert general._host_allowed("v2.example.com", "example.com")[0] is True


def test_builtin_rejects_unresolvable_host(monkeypatch):
    """解析不了就拒绝：判不出目标是不是内网，不能放行。"""
    def boom(host, port):
        raise general.socket.gaierror("nxdomain")

    monkeypatch.setattr(general.socket, "getaddrinfo", boom)
    ok, reason = general._host_allowed("no-such-host.invalid", "")
    assert ok is False
    assert "无法解析" in reason


def test_builtin_rejects_missing_host():
    ok, reason = general._host_allowed("", "")
    assert ok is False
    assert "主机名" in reason


# --------------------------------------------------------------------------- 两层规则必须一致

@pytest.mark.parametrize("host,pattern,expected", [
    ("api.example.com", "api.example.com", True),
    ("v2.api.example.com", "api.example.com", True),
    ("notapi.example.com", "api.example.com", False),
    ("example.com", "example.com", True),
    ("x.openai.com", "*.openai.com", True),
    ("a.b.openai.com", "*.openai.com", True),
    # 显式通配**不含根域**（与 TLS 通配证书语义一致）：要连根域就再写一条
    ("openai.com", "*.openai.com", False),
    ("evilexample.com", "example.com", False),
])
def test_both_layers_match_identically(host, pattern, expected):
    """同一个 pattern 在两层必须给出同一个答案。

    allowed_hosts 在项目里有两种用法（工具行闸门 / 内置 http_request 的能力配置）。
    规则一旦分叉，管理员按文档填了在 A 处生效、B 处不生效，而且**都不报错** ——
    这是最典型的静默失效。此用例是本文件存在的主要理由。

    实际发现过的分叉（已修）：
    - 内置侧 `*.openai.com` 曾额外放行根域 openai.com，闸门那边不放行；
    - 内置侧不做隐式后缀匹配（example.com 不覆盖 v2.example.com），闸门那边做。
    """
    from app.tools.permission import _host_matches
    from app.tools.general import _pattern_matches

    assert _host_matches(host, pattern) is expected, f"permission 层: {host} vs {pattern}"
    assert _pattern_matches(host, pattern) is expected, f"builtin 层: {host} vs {pattern}"

