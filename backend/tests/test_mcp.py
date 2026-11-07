"""MCP 连接器（docs/17 §5，P5）：同步语义、执行分支、闸门、参数降级。

不发真实网络请求：MCP 客户端那一层整体打桩（app.mcp.client.probe / call），
测的是"同步怎么 upsert"、"执行怎么分发"、"闸门怎么判"，这三处才是会静默出错的地方。
远端协议本身由官方 SDK 负责，不在本用例的范围内。
"""
import pytest

from app.db.models import McpServer, Tool
from app.mcp import client as mcp_client
from app.services import mcp_service, tool_service
from app.tools import executor
from app.tools.permission import ToolCallContext


# --------------------------------------------------------------------------- 参数转换

def test_nested_schema_degrades_to_text_instead_of_dropping():
    """嵌套对象 / 数组必须降级成文本并保留描述，不能直接丢参。

    丢了的话模型会漏传必填项，远端调用必然失败；降级成文本至少还能让模型传 JSON 字符串。
    """
    params, notes, degraded = mcp_service._to_tool_parameters({
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "查询"},
            "filter": {"type": "object", "description": "过滤条件"},
            "tags": {"type": "array", "description": "标签"},
        },
        "required": ["q", "filter"],
    })
    assert params["properties"]["q"]["type"] == "string"
    assert params["properties"]["filter"]["type"] == "string"
    assert "JSON 字符串" in params["properties"]["filter"]["description"]
    assert params["properties"]["tags"]["type"] == "string"
    # 降级后的参数仍然是可声明的，required 要保留
    assert set(params["required"]) == {"q", "filter"}
    assert len(notes) == 2
    # 降级参数名要单独记下来：调用前要按 JSON 解析回数组 / 对象，否则远端收到的是字符串
    assert set(degraded) == {"filter", "tags"}


def test_enum_only_kept_for_string_and_required_pruned():
    """enum 只对 string 有意义；required 里指向不存在参数的项要摘掉（否则声明本身不合法）。"""
    params, _, _ = mcp_service._to_tool_parameters({
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["a", "b"]}, "n": {"type": "integer", "enum": [1, 2]}},
        "required": ["mode", "ghost"],
    })
    assert params["properties"]["mode"]["enum"] == ["a", "b"]
    assert "enum" not in params["properties"]["n"]   # 非 string 的枚举丢掉
    assert params["required"] == ["mode"]            # ghost 不存在，摘掉


def test_illegal_property_name_is_skipped_with_note():
    """参数名不合法时忽略并说明：本项目声明要求 ^[A-Za-z_][A-Za-z0-9_]*$。"""
    params, notes, _ = mcp_service._to_tool_parameters({
        "type": "object",
        "properties": {"bad-name": {"type": "string"}, "good": {"type": "string"}},
    })
    assert "bad-name" not in params["properties"]
    assert "good" in params["properties"]
    assert any("bad-name" in n for n in notes)


def test_degraded_params_restored_before_forwarding():
    """降级成文本的数组 / 对象参数，转发前要按 JSON 解析回去。

    只校验不还原的话：模型传 ["a","b"] 会被校验拒掉；传 '["a","b"]' 通过校验，
    但远端收到的是字符串而不是数组，调用必然失败 —— 而且报错来自远端，看不出是这边的转换问题。
    """
    tool = Tool(name="pytest_mcp_restore", description="d", type="mcp", is_enabled=True,
                config={
                    "allowed_hosts": ["mcp.example.com"], "url": "https://mcp.example.com/mcp",
                    "parameters": {"type": "object", "properties": {
                        "tags": {"type": "string"}, "user": {"type": "string"}, "plain": {"type": "string"},
                    }, "required": []},
                    "degraded_params": ["tags", "user"],
                },
                mcp_server_id=1, remote_name="x")
    args = mcp_service.build_call_args(tool, {
        "tags": '["a", "b"]',
        "user": '{"id": 7}',
        "plain": "普通文本",
    })
    assert args["tags"] == ["a", "b"]      # 解析回真数组
    assert args["user"] == {"id": 7}        # 解析回真对象
    assert args["plain"] == "普通文本"       # 没降级的保持原样


def test_degraded_param_kept_when_not_json():
    """不是合法 JSON 时原样转发：远端可能本来就要一个普通字符串，不该在本地拒掉。"""
    tool = Tool(name="pytest_mcp_restore2", description="d", type="mcp", is_enabled=True,
                config={
                    "allowed_hosts": ["mcp.example.com"], "url": "https://mcp.example.com/mcp",
                    "parameters": {"type": "object", "properties": {"tags": {"type": "string"}}, "required": []},
                    "degraded_params": ["tags"],
                },
                mcp_server_id=1, remote_name="x")
    args = mcp_service.build_call_args(tool, {"tags": "not json"})
    assert args["tags"] == "not json"


def test_tool_name_is_sanitised_and_bounded():
    """本地工具名要能出现在模型的 tool_calls 里：只留字母数字、下划线与连字符，且不超过 128 字符。

    **连字符必须保留**：它被模型 API 明确允许（OpenAI 函数名规则 ^[a-zA-Z0-9_-]+$），
    清洗掉不仅难读，还会把 `pytest-` 前缀打成 `pytest_`，让测试回收的按前缀匹配失效
    （2026-11-07 因此漏出 33 个孤儿工具）。
    """
    name = mcp_service._tool_name("my server", "some.tool/name")
    assert name == "my_server_some_tool_name"
    # 连字符原样保留，空格与点斜杠才换下划线
    assert mcp_service._tool_name("pytest-mcp-x", "do-it") == "pytest-mcp-x_do-it"
    long_name = mcp_service._tool_name("s" * 80, "t" * 200)
    assert len(long_name) <= 128


# --------------------------------------------------------------------------- 校验

def test_allowed_hosts_is_mandatory(client, auth_headers):
    """白名单为空必须 400：MCP 地址是外部输入，空名单等于闸门不存在。

    与 HTTP 工具不同（那边空名单是历史遗留的"放行但 WARN"窗口），这里从一开始就收死。
    """
    res = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-nohosts", "url": "https://mcp.example.com/mcp", "allowed_hosts": [],
    })
    assert res.status_code == 400, res.text
    assert "allowed_hosts" in res.text


def test_non_http_scheme_rejected(client, auth_headers):
    """stdio 不支持：地址必须是 http/https。"""
    res = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-stdio", "url": "stdio://npx something", "allowed_hosts": ["x.com"],
    })
    assert res.status_code == 400, res.text


def test_secret_header_rejected(client, auth_headers):
    """请求头里写 Token 必须拒绝：凭据要走 secret（加密存、接口不回传）。"""
    res = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-hdr", "url": "https://mcp.example.com/mcp",
        "allowed_hosts": ["mcp.example.com"], "headers": {"Authorization": "Bearer leak"},
    })
    assert res.status_code == 400, res.text
    assert "凭据" in res.text


def test_secret_never_returned(client, auth_headers):
    """凭据任何接口都不回传，只回 has_secret（与 tools.auth 同一口径）。"""
    created = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-secret-" + __import__("uuid").uuid4().hex[:6],
        "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"],
        "secret": "super-secret-token",
    })
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["has_secret"] is True
    assert "super-secret-token" not in created.text
    client.delete(f"/api/v1/mcp-servers/{body['id']}", headers=auth_headers)


def test_caller_cannot_manage(client, caller_headers):
    """caller 角色不能管 MCP 服务器（管理接口）。"""
    res = client.get("/api/v1/mcp-servers", headers=caller_headers)
    assert res.status_code == 403, res.text


# --------------------------------------------------------------------------- 同步

def test_sync_creates_tools_disabled(client, auth_headers, monkeypatch):
    """同步出来的工具默认停用：远端工具描述是外部输入，先由人看过再启用。"""
    server = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-new-" + __import__("uuid").uuid4().hex[:6],
        "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"],
    })
    sid = server.json()["id"]

    async def fake_probe(url, transport, headers, secret, timeout):
        return [mcp_client.McpTool(name="search", description="搜索",
                                   input_schema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]})]

    monkeypatch.setattr(mcp_client, "probe", fake_probe)
    try:
        res = client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
        assert res.status_code == 200, res.text
        detail = client.get(f"/api/v1/mcp-servers/{sid}", headers=auth_headers).json()
        assert len(detail["tools"]) == 1
        assert detail["tools"][0]["is_enabled"] is False
        assert detail["last_synced_at"] is not None
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)


def test_sync_upsert_semantics(client, auth_headers, monkeypatch):
    """远端有 / 库里有 / 远端消失 三种情况的行为必须分开。"""
    server = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-sync-" + __import__("uuid").uuid4().hex[:6],
        "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"],
    })
    assert server.status_code == 200, server.text
    sid = server.json()["id"]

    calls = {"n": 0}

    async def fake_probe(url, transport, headers, secret, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                mcp_client.McpTool(name="alpha", description="A", input_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}),
                mcp_client.McpTool(name="beta", description="B", input_schema={"type": "object", "properties": {}}),
            ]
        # 第二次：alpha 描述变了、beta 消失、gamma 新增
        return [
            mcp_client.McpTool(name="alpha", description="A 改了", input_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}),
            mcp_client.McpTool(name="gamma", description="C", input_schema={"type": "object", "properties": {}}),
        ]

    monkeypatch.setattr(mcp_client, "probe", fake_probe)
    try:
        first = client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
        assert first.status_code == 200, first.text
        assert first.json() == {"created": 2, "updated": 0, "disabled": 0, "unchanged": 0, "total": 2}

        detail = client.get(f"/api/v1/mcp-servers/{sid}", headers=auth_headers).json()
        by_remote = {t["remote_name"]: t for t in detail["tools"]}
        assert set(by_remote) == {"alpha", "beta"}
        assert all(not t["is_enabled"] for t in detail["tools"]), "新建的工具必须默认停用"

        # 人工启用 alpha 与 beta：alpha 用来验证同步不改人做的决定，
        # beta 用来验证"远端消失 → 停用"（本来就停用的不会计入 disabled，所以必须先启用）
        client.post(f"/api/v1/tools/{by_remote['alpha']['id']}/toggle", headers=auth_headers)
        client.post(f"/api/v1/tools/{by_remote['beta']['id']}/toggle", headers=auth_headers)

        second = client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
        assert second.status_code == 200, second.text
        assert second.json() == {"created": 1, "updated": 1, "disabled": 1, "unchanged": 0, "total": 2}

        detail2 = client.get(f"/api/v1/mcp-servers/{sid}", headers=auth_headers).json()
        by_remote2 = {t["remote_name"]: t for t in detail2["tools"]}
        assert set(by_remote2) == {"alpha", "beta", "gamma"}   # beta 不删除，只停用
        assert by_remote2["alpha"]["is_enabled"] is True        # 人工启用状态被保留
        assert by_remote2["alpha"]["description"] == "A 改了"
        assert by_remote2["beta"]["is_enabled"] is False
        assert by_remote2["gamma"]["is_enabled"] is False
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)


def test_sync_failure_records_last_error(client, auth_headers, monkeypatch):
    """远端不可达时写 last_error 并 502，而不是 500 —— 页面要能看到失败原因。"""
    server = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-fail-" + __import__("uuid").uuid4().hex[:6],
        "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"],
    })
    sid = server.json()["id"]

    async def boom(*a, **kw):
        raise mcp_client.McpError("连接 MCP 服务器失败：ConnectError")

    monkeypatch.setattr(mcp_client, "probe", boom)
    try:
        res = client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
        assert res.status_code == 502, res.text
        assert "ConnectError" in res.text
        detail = client.get(f"/api/v1/mcp-servers/{sid}", headers=auth_headers).json()
        assert "ConnectError" in (detail["last_error"] or "")
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)


def test_disabled_server_cannot_sync(client, auth_headers):
    """停用的服务器不允许同步：先启用再同步，避免"关着的东西还在后台连外部"。"""
    server = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-off-" + __import__("uuid").uuid4().hex[:6],
        "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"], "is_enabled": False,
    })
    sid = server.json()["id"]
    try:
        res = client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
        assert res.status_code == 400, res.text
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)


# --------------------------------------------------------------------------- 执行与闸门

def test_execute_dispatches_mcp_and_returns_error_when_server_gone(client, auth_headers, monkeypatch):
    """执行分支：type='mcp' 走 _execute_mcp；服务器被删时返回 error 而不是抛异常。"""
    called = {"n": 0}

    async def fake_call(*a, **kw):
        called["n"] += 1
        return {"result": "ok"}

    monkeypatch.setattr(mcp_client, "call", fake_call)
    # 必须配 allowed_hosts：闸门在分发之前判，没配就轮不到"服务器已删除"这一层
    tool = Tool(name="pytest_tool_orphan", description="d", type="mcp",
                config={"allowed_hosts": ["mcp.example.com"], "url": "https://mcp.example.com/mcp"},
                mcp_server_id=999999, remote_name="x", is_enabled=True)
    result = __import__("asyncio").run(executor.execute_tool(tool, {}, ToolCallContext(tool=tool, source="chat")))
    assert "error" in result
    assert "服务器已被删除" in result["error"]
    assert called["n"] == 0


def test_mcp_tool_passes_gate_and_calls_remote(client, auth_headers, monkeypatch):
    """正常路径：闸门放行 → 调远端 → 返回 result。同时验证 allowed_hosts 生效。"""
    server = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-exec-" + __import__("uuid").uuid4().hex[:6],
        "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"],
    })
    sid = server.json()["id"]

    async def fake_probe(*a, **kw):
        return [mcp_client.McpTool(name="echo", description="回声", input_schema={"type": "object", "properties": {"t": {"type": "string"}}, "required": ["t"]})]

    async def fake_call(url, transport, headers, secret, timeout, name, args):
        assert name == "echo"
        assert args == {"t": "hi"}
        return {"result": "hi"}

    monkeypatch.setattr(mcp_client, "probe", fake_probe)
    monkeypatch.setattr(mcp_client, "call", fake_call)
    try:
        assert client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers).status_code == 200
        detail = client.get(f"/api/v1/mcp-servers/{sid}", headers=auth_headers).json()
        tid = detail["tools"][0]["id"]
        client.post(f"/api/v1/tools/{tid}/toggle", headers=auth_headers)

        # 工具页测试调用走 admin_test 来源
        res = client.post(f"/api/v1/tools/{tid}/test", headers=auth_headers, json={"args": {"t": "hi"}})
        assert res.status_code == 200, res.text
        assert res.json()["data"]["result"] == {"result": "hi"}
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)


def test_share_source_denied_for_mcp_tool():
    """分享访客不装配外部工具：MCP 工具在 share 来源下必须被闸门拒绝。"""
    tool = Tool(name="pytest_mcp_share", description="d", type="mcp", is_enabled=True,
                config={"allowed_hosts": ["mcp.example.com"], "url": "https://mcp.example.com/mcp"},
                mcp_server_id=1, remote_name="x")
    result = __import__("asyncio").run(executor.execute_tool(tool, {}, ToolCallContext(tool=tool, source="share")))
    assert "error" in result
    assert result.get("denied") is True


def test_mcp_tool_without_allowed_hosts_denied():
    """没配白名单的 MCP 工具一律拒绝（与 HTTP 工具 2026-10-26 的收口一致）。"""
    tool = Tool(name="pytest_mcp_nohosts", description="d", type="mcp", is_enabled=True,
                config={"url": "https://mcp.example.com/mcp"}, mcp_server_id=1, remote_name="x")
    result = __import__("asyncio").run(executor.execute_tool(tool, {}, ToolCallContext(tool=tool, source="chat")))
    assert "error" in result
    assert "allowed_hosts" in result["error"]


def test_mcp_tool_args_validated_before_call(client, auth_headers, monkeypatch):
    """参数不符合声明时不发起远端调用，直接把错误回给模型。"""
    called = {"n": 0}

    async def fake_call(*a, **kw):
        called["n"] += 1
        return {"result": "should not happen"}

    monkeypatch.setattr(mcp_client, "call", fake_call)
    tool = Tool(name="pytest_mcp_args", description="d", type="mcp", is_enabled=True,
                config={"allowed_hosts": ["mcp.example.com"], "url": "https://mcp.example.com/mcp",
                        "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}},
                mcp_server_id=1, remote_name="x")
    result = __import__("asyncio").run(executor.execute_tool(tool, {"n": "not-a-number"}, ToolCallContext(tool=tool, source="chat")))
    assert "error" in result
    assert "参数校验失败" in result["error"]
    assert called["n"] == 0


# --------------------------------------------------------------------------- 工具页展示

def test_tool_row_carries_mcp_source(client, auth_headers, monkeypatch):
    """工具页要能显示「MCP · 某某服务器」：列表项带 mcp_server_id / remote_name / mcp_server_name。"""
    server_name = "pytest-mcp-label-" + __import__("uuid").uuid4().hex[:6]
    server = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": server_name, "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"],
    })
    sid = server.json()["id"]

    async def fake_probe(*a, **kw):
        return [mcp_client.McpTool(name="labelled", description="带标签的", input_schema={"type": "object", "properties": {}})]

    monkeypatch.setattr(mcp_client, "probe", fake_probe)
    try:
        client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
        # 工具名是 {server}_{remote}，且连字符会被换成下划线（要能出现在模型的 tool_calls 里），
        # 所以按 server_name 搜不到，得按清洗后的名字搜
        local_name = mcp_service._tool_name(server_name, "labelled")
        res = client.get("/api/v1/tools", headers=auth_headers, params={"q": local_name, "page_size": 100})
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        row = items[0]
        assert row["type"] == "mcp"
        assert row["mcp_server_id"] == sid
        assert row["remote_name"] == "labelled"
        assert row["mcp_server_name"] == server_name
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)


def test_delete_server_keeps_tools_disabled(client, auth_headers, monkeypatch):
    """删服务器不删工具：工具保留但停用，避免破坏智能体的 tool_ids 引用。"""
    server = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-del-" + __import__("uuid").uuid4().hex[:6],
        "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"],
    })
    sid = server.json()["id"]

    async def fake_probe(*a, **kw):
        return [mcp_client.McpTool(name="survivor", description="活下来的", input_schema={"type": "object", "properties": {}})]

    monkeypatch.setattr(mcp_client, "probe", fake_probe)
    client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
    detail = client.get(f"/api/v1/mcp-servers/{sid}", headers=auth_headers).json()
    tid = detail["tools"][0]["id"]
    client.post(f"/api/v1/tools/{tid}/toggle", headers=auth_headers)   # 先启用

    assert client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers).status_code == 200

    row = client.get(f"/api/v1/tools/{tid}", headers=auth_headers).json()
    assert row["is_enabled"] is False
    assert row["config"].get("source_deleted") is True


def test_sync_reports_unchanged_instead_of_updated(client, auth_headers, monkeypatch):
    """同样的远端清单同步两次：第二次必须报 unchanged，而不是又"更新了 N 个"。

    否则使用者点一次同步就看到"更新了 4 个"，会以为远端变了 —— 实际什么都没动，
    这个数字就完全失去了诊断价值。
    """
    server = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": "pytest-mcp-unchanged-" + __import__("uuid").uuid4().hex[:6],
        "url": "https://mcp.example.com/mcp", "allowed_hosts": ["mcp.example.com"],
    })
    sid = server.json()["id"]

    async def fake_probe(*a, **kw):
        return [mcp_client.McpTool(name="same", description="没变",
                                   input_schema={"type": "object", "properties": {"q": {"type": "string"}}})]

    monkeypatch.setattr(mcp_client, "probe", fake_probe)
    try:
        first = client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
        assert first.status_code == 200, first.text
        assert first.json()["created"] == 1

        second = client.post(f"/api/v1/mcp-servers/{sid}/sync", headers=auth_headers)
        assert second.status_code == 200, second.text
        body = second.json()
        assert body["unchanged"] == 1, body
        assert body["updated"] == 0, body
        assert body["created"] == 0, body
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)

