"""MCP 傻瓜化：粘贴识别、一键启用、同步即启用（docs/17 §5）。

这三件事的共同目标是"少让使用者做决定"：
- 粘贴识别：手上有什么就粘什么，不用自己拆成五个字段
- 一键启用：信任一台服务器是一个整体决定，不该逐个点十几个开关
- 同步即启用：新建后的标准动作合成一步

共同的风险是"猜错了还静默生效"，因此每条都验"猜不出来时明确报错"。
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.mcp import import_config
from app.mcp import client as mcp_client
from tests import local_mcp


# --------------------------------------------------------------------------- 粘贴识别：能认的形态

def test_parse_bare_url_guesses_transport_and_hosts():
    """只粘一个地址：地址原样用、传输按路径猜、白名单自动取主机名。

    白名单是最容易被漏填的字段（漏了后端 400），从地址里自动推导能省掉一次往返。
    """
    out = import_config.parse_config("https://mcp.example.com/mcp")
    assert out["url"] == "https://mcp.example.com/mcp"
    assert out["transport"] == "http"
    assert out["allowed_hosts"] == ["mcp.example.com"]
    assert out["notes"], "要给使用者一句说明，不能默默填完"


def test_parse_sse_url_guesses_sse():
    """路径以 /sse 结尾时推断成 SSE 传输，否则使用者要自己知道这个区别。"""
    assert import_config.parse_config("https://mcp.example.com/sse")["transport"] == "sse"


def test_parse_mcp_servers_json():
    """Claude / Cursor 的 mcpServers 结构：取第一个服务器，名字也带出来。"""
    text = json.dumps({"mcpServers": {"github": {
        "url": "https://mcp.example.com/mcp",
        "headers": {"X-Tenant": "acme"},
    }}})
    out = import_config.parse_config(text)
    assert out["name"] == "github"
    assert out["url"] == "https://mcp.example.com/mcp"
    assert out["headers"] == {"X-Tenant": "acme"}
    assert out["allowed_hosts"] == ["mcp.example.com"]


def test_parse_extracts_bearer_token_to_secret():
    """Authorization: Bearer xxx 里的 token 要提进「凭据」，不能留在请求头。

    留在请求头的话后端会 400 拒绝（请求头会原样回传），使用者会以为这是平台的 bug。
    """
    text = json.dumps({"mcpServers": {"gh": {
        "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": "Bearer ghp_secret123"},
    }}})
    out = import_config.parse_config(text)
    assert out["secret"] == "ghp_secret123"
    assert "Authorization" not in out["headers"]


def test_parse_extracts_top_level_token():
    """有些人写的是 {"url": ..., "token": ...}，顶层 token 也要认。"""
    out = import_config.parse_config(json.dumps({"url": "https://x.example.com/mcp", "token": "sk-abc"}))
    assert out["secret"] == "sk-abc"


def test_parse_url_plus_token_two_lines():
    """「地址 + 凭据」两行：地址取第一行、token 从剩余文本里找。"""
    out = import_config.parse_config("https://mcp.example.com/mcp\nBearer tok123")
    assert out["url"] == "https://mcp.example.com/mcp"
    assert out["secret"] == "tok123"


# --------------------------------------------------------------------------- 粘贴识别：必须拒绝的形态

def test_parse_rejects_stdio_command():
    """npx / uvx 这类 stdio 启动命令要明确拒绝并说清为什么，不能当成地址用。

    如果静默失败或者塞进 url 字段，使用者会看到一堆看不懂的报错。
    """
    with pytest.raises(import_config.McpConfigError) as ei:
        import_config.parse_config("npx -y @modelcontextprotocol/server-github")
    msg = str(ei.value)
    assert "stdio" in msg
    # 要说清为什么不支持，而不只是"不支持"
    assert "执行" in msg


def test_parse_rejects_stdio_json_entry():
    """mcpServers 里 command + args 形式的条目同样拒绝。"""
    text = json.dumps({"mcpServers": {"x": {"command": "npx", "args": ["-y", "server-x"]}}})
    with pytest.raises(import_config.McpConfigError) as ei:
        import_config.parse_config(text)
    assert "stdio" in str(ei.value)


def test_parse_rejects_non_bearer_authorization():
    """Authorization 不是 Bearer 时不能猜：本平台只按 Bearer 发，擅自改写会一直 401。"""
    text = json.dumps({"url": "https://x.example.com/mcp", "headers": {"Authorization": "Basic dXNlcjpwYXNz"}})
    with pytest.raises(import_config.McpConfigError) as ei:
        import_config.parse_config(text)
    assert "Bearer" in str(ei.value)


def test_parse_rejects_unknown_text():
    """完全认不出来的内容：报错要列出支持哪三种形式，而不是只说"格式错误"。"""
    with pytest.raises(import_config.McpConfigError) as ei:
        import_config.parse_config("随便写点什么")
    msg = str(ei.value)
    assert "地址" in msg or "URL" in msg


def test_parse_rejects_empty():
    with pytest.raises(import_config.McpConfigError):
        import_config.parse_config("   ")


def test_parse_rejects_non_http_scheme():
    with pytest.raises(import_config.McpConfigError):
        import_config.parse_config(json.dumps({"url": "ftp://x.example.com/mcp"}))


# --------------------------------------------------------------------------- 路由层

def test_parse_endpoint_does_not_write(client, auth_headers):
    """粘贴识别不落库：调完库里不该多出服务器。"""
    before = client.get("/api/v1/mcp-servers", headers=auth_headers, params={"page_size": 1}).json()["total"]
    res = client.post("/api/v1/mcp-servers/parse", headers=auth_headers,
                      json={"text": "https://mcp.example.com/mcp"})
    assert res.status_code == 200, res.text
    assert res.json()["allowed_hosts"] == ["mcp.example.com"]
    after = client.get("/api/v1/mcp-servers", headers=auth_headers, params={"page_size": 1}).json()["total"]
    assert after == before


def test_parse_endpoint_returns_400_with_reason(client, auth_headers):
    """识别失败是 400 带原因（前端直接把 detail 上屏），不是 500。"""
    res = client.post("/api/v1/mcp-servers/parse", headers=auth_headers,
                      json={"text": "npx -y something"})
    assert res.status_code == 400, res.text
    assert "stdio" in res.text


def test_caller_cannot_parse(client, caller_headers):
    """粘贴识别也是管理接口：caller 403。"""
    assert client.post("/api/v1/mcp-servers/parse", headers=caller_headers,
                       json={"text": "https://x.com/mcp"}).status_code == 403


# --------------------------------------------------------------------------- 一键启用

@pytest.fixture(scope="module")
def live() -> local_mcp.LocalMcp:
    srv = local_mcp.start()
    try:
        yield srv
    finally:
        srv.stop()


@pytest.fixture
def server(client, auth_headers, live):
    name = "pytest-mcp-bulk-" + uuid.uuid4().hex[:6]
    res = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": name, "url": live.url, "transport": "http", "allowed_hosts": ["127.0.0.1"],
    })
    assert res.status_code == 200, res.text
    sid = res.json()["id"]
    try:
        yield sid
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)


def test_enable_all_enables_every_synced_tool(client, auth_headers, server):
    """一键启用：该服务器名下全部工具变启用。

    没有这个接口时，一台服务器十几个工具要逐个点开关 —— 这是新用户最容易放弃的地方。
    """
    client.post(f"/api/v1/mcp-servers/{server}/sync", headers=auth_headers)
    res = client.post(f"/api/v1/mcp-servers/{server}/tools/enable-all", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 4
    assert body["changed"] == 4

    detail = client.get(f"/api/v1/mcp-servers/{server}", headers=auth_headers).json()
    assert all(t["is_enabled"] for t in detail["tools"])


def test_enable_all_is_idempotent(client, auth_headers, server):
    """再调一次不报错、changed 为 0（重复提交要幂等）。"""
    client.post(f"/api/v1/mcp-servers/{server}/sync", headers=auth_headers)
    client.post(f"/api/v1/mcp-servers/{server}/tools/enable-all", headers=auth_headers)
    again = client.post(f"/api/v1/mcp-servers/{server}/tools/enable-all", headers=auth_headers)
    assert again.status_code == 200, again.text
    assert again.json()["changed"] == 0


def test_disable_all(client, auth_headers, server):
    """一键停用反向也要有。"""
    client.post(f"/api/v1/mcp-servers/{server}/sync", headers=auth_headers)
    client.post(f"/api/v1/mcp-servers/{server}/tools/enable-all", headers=auth_headers)
    res = client.post(f"/api/v1/mcp-servers/{server}/tools/disable-all", headers=auth_headers)
    assert res.status_code == 200, res.text
    detail = client.get(f"/api/v1/mcp-servers/{server}", headers=auth_headers).json()
    assert all(not t["is_enabled"] for t in detail["tools"])


def test_enable_all_only_touches_own_tools(client, auth_headers, server):
    """只动这台服务器名下的工具，不能波及其它服务器或手工建的工具。

    这种"范围溢出"是静默失效里最危险的一类：一旦误伤，别人的工具会在没人察觉时被打开或关掉。
    """
    # 手工建一个 HTTP 工具（不属于任何服务器），建完先停用 —— ToolIn 不接 is_enabled，默认启用
    http_tool = client.post("/api/v1/tools", headers=auth_headers, json={
        "name": "pytest-mcp-untouched-" + uuid.uuid4().hex[:6],
        "description": "手工工具", "type": "http",
        "config": {"url": "https://api.example.com/x", "method": "GET", "allowed_hosts": ["api.example.com"]},
    })
    assert http_tool.status_code == 200, http_tool.text
    tid = http_tool.json()["id"]
    client.post(f"/api/v1/tools/{tid}/toggle", headers=auth_headers)

    client.post(f"/api/v1/mcp-servers/{server}/sync", headers=auth_headers)
    client.post(f"/api/v1/mcp-servers/{server}/tools/enable-all", headers=auth_headers)

    row = client.get(f"/api/v1/tools/{tid}", headers=auth_headers)
    if row.status_code == 200:
        assert row.json()["is_enabled"] is False, "一键启用不能碰到手工建的工具"
        client.delete(f"/api/v1/tools/{tid}", headers=auth_headers)


def test_sync_and_enable_does_both(client, auth_headers, server):
    """同步 + 启用合成一步：返回里同时有同步计数与启用计数。"""
    res = client.post(f"/api/v1/mcp-servers/{server}/sync-and-enable", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 4
    assert body["enabled_tools"] == 4
    assert body["tools_total"] == 4

    detail = client.get(f"/api/v1/mcp-servers/{server}", headers=auth_headers).json()
    assert all(t["is_enabled"] for t in detail["tools"])


def test_sync_and_enable_propagates_remote_failure(client, auth_headers, monkeypatch, server):
    """远端连不上时 sync-and-enable 要原样抛出 502，不能把"没同步到"说成成功。

    否则页面会显示"已启用 0 个工具"看起来像成功，实际一个都没拉到。
    """
    async def boom(*a, **kw):
        raise mcp_client.McpError("连不上 MCP 服务器 x：地址或端口不对")

    monkeypatch.setattr(mcp_client, "probe", boom)
    res = client.post(f"/api/v1/mcp-servers/{server}/sync-and-enable", headers=auth_headers)
    assert res.status_code == 502, res.text
    assert "连不上" in res.text


def test_caller_cannot_enable_all(client, caller_headers, server):
    assert client.post(f"/api/v1/mcp-servers/{server}/tools/enable-all",
                       headers=caller_headers).status_code == 403
