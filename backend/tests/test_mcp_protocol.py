"""MCP 协议层测试（docs/17 §5.5）：对**真实的本地 MCP 服务器**跑通整条链路。

与 test_mcp.py 的分工：
- `test_mcp.py` 把客户端打桩，测"同步怎么 upsert"、"执行怎么分发"、"闸门怎么判"
- 本文件起一个真的 MCP 服务器（官方 SDK 的 MCPServer + Streamable HTTP + uvicorn），
  测握手、tools/list、tools/call、凭据头、远端报错映射

为什么必须有这一层：2026-11-08 之前客户端层是零协议验证的。风险在于 SDK 升级、
传输选错、头没带上这类问题**测试全绿而线上全挂** —— 报错还来自远端，看不出是本地问题。
补这一层当天就抓到一个真 P0：连不上时 CancelledError 穿透所有 except Exception，
最终返回 **500 空响应体**，页面只看到"同步失败"看不到原因。
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.db.models import McpServer, Tool
from app.mcp import client as mcp_client
from app.services import mcp_service, tool_service
from app.tools import executor
from app.tools.permission import ToolCallContext
from tests import local_mcp


@pytest.fixture(scope="module")
def live() -> local_mcp.LocalMcp:
    """整个模块共用一个本地 MCP 服务器：起一次约 1 秒，每个用例起一次太慢。"""
    srv = local_mcp.start(recorder=[])
    try:
        yield srv
    finally:
        srv.stop()


# --------------------------------------------------------------------------- 协议本身

def test_probe_reads_real_tool_list(live):
    """真实握手 + tools/list：能拿到工具名、描述、inputSchema。

    这不是"SDK 应该没问题"就能省掉的断言：probe 要把 SDK 的 Tool 对象转成 McpTool，
    字段名在 SDK 大版本之间改过（inputSchema → input_schema 是 1.x → 2.x 的改动之一），
    转换写错时所有工具的参数都会变成空对象，模型随即漏传所有必填项。
    """
    tools = asyncio.run(mcp_client.probe(live.url, "http", {}, None, 10.0))
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {"echo", "add", "tags", "boom"}
    assert by_name["echo"].description
    # 参数声明必须真的带出来
    assert by_name["add"].input_schema["properties"]["a"]["type"] == "integer"
    assert set(by_name["add"].input_schema.get("required") or []) == {"a", "b"}


def test_call_roundtrip(live):
    """真实 tools/call：参数送达、返回值取出来。"""
    result = asyncio.run(mcp_client.call(live.url, "http", {}, None, 10.0, "echo", {"text": "你好"}))
    assert result == {"result": "echo:你好"}


def test_call_sends_nested_args_intact(live):
    """数组参数必须原样送到远端（不是被降级成字符串）。

    这是同步时把 array 降级成 string、调用前再 JSON 还原的闭环验证：
    只要还原那一步漏了，远端收到 '["x","y"]' 这个字符串，会报类型错误 ——
    而错误信息来自远端，看起来像"对方服务有问题"。
    Args 直接给数组走的是未降级路径；这里验它确实到达。
    """
    result = asyncio.run(mcp_client.call(live.url, "http", {}, None, 10.0, "tags", {"tags": ["a", "b"]}))
    assert result == {"result": "a,b"}


def test_remote_tool_error_maps_to_error_key(live):
    """远端工具抛异常时必须返回 {"error": ...}，不能抛出来炸掉整轮对话。

    抛出去的话这一轮对话直接失败，模型连"换个做法"的机会都没有。
    """
    result = asyncio.run(mcp_client.call(live.url, "http", {}, None, 10.0, "boom", {}))
    assert "error" in result
    assert "result" not in result


def test_unknown_tool_is_error_not_crash(live):
    """调一个远端没有的工具：返回 error，且文案能看出是"工具不存在"。"""
    result = asyncio.run(mcp_client.call(live.url, "http", {}, None, 10.0, "nope", {}))
    assert "error" in result
    assert "Unknown tool" in result["error"] or "不存在" in result["error"]


# --------------------------------------------------------------------------- 凭据与错误翻译

def test_auth_headers_adds_bearer_and_keeps_custom():
    """凭据走 Authorization: Bearer，自定义头原样保留。拼错这一处 = 所有 MCP 调用 401。"""
    assert mcp_client._auth_headers({}, "s3cret") == {"Authorization": "Bearer s3cret"}
    assert mcp_client._auth_headers({"X-Tenant": "acme"}, None) == {"X-Tenant": "acme"}
    assert mcp_client._auth_headers({"X-Tenant": "acme"}, "s3cret") == {
        "X-Tenant": "acme", "Authorization": "Bearer s3cret",
    }


def test_connect_failure_is_human_readable():
    """连不上时给人话 + 具体地址，而不是 500 空响应体。

    2026-11-08 之前：SDK 内部 anyio cancel scope 抛的 CancelledError（BaseException）
    穿透所有 except Exception，一路冒到 FastAPI → 500 且 body 为空。
    页面只显示"同步失败"，用户完全不知道是地址写错还是服务没起。
    """
    with pytest.raises(mcp_client.McpError) as ei:
        asyncio.run(mcp_client.probe("http://127.0.0.1:1/mcp", "http", {}, None, 3.0))
    msg = str(ei.value)
    assert "127.0.0.1:1" in msg          # 说清是哪个地址
    assert "连不上" in msg                # 说清是什么事
    # 不能是空串，也不能只是类名
    assert len(msg) > 15


def test_http_error_status_translated():
    """HTTP 状态码翻成"该去改哪里"：404 要提示检查路径，而不是只回一个数字。"""
    assert "404" in mcp_client._status_hint(404)
    assert "/mcp" in mcp_client._status_hint(404)
    assert "凭据" in mcp_client._status_hint(401)
    assert "限流" in mcp_client._status_hint(429)
    # 5xx 要明确不是本平台的问题，否则用户会去查本平台的日志
    assert "不是本平台" in mcp_client._status_hint(502)


def test_wrap_error_unwraps_exception_group():
    """SDK 的报错常是 ExceptionGroup 套真因，拆包后要能拿到根因而不是只显示 "ExceptionGroup"。"""
    root = ValueError("真正的根因")
    group = BaseExceptionGroup("外层", [root])
    wrapped = mcp_client._wrap_error(group)  # type: ignore[arg-type]
    assert "真正的根因" in str(wrapped)


def test_content_to_text_skips_binary_and_truncates():
    """图片 / 资源不展开（会把上下文撑爆），超长文本截断并注明原文长度。"""

    class Part:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    text = mcp_client._content_to_text([
        Part(type="text", text="第一段"),
        Part(type="image", mime_type="image/png"),
        Part(type="resource", resource=Part(text="资源正文")),
    ])
    assert "第一段" in text
    assert "图片" in text and "未展开" in text
    assert "资源正文" in text

    long = mcp_client._content_to_text([Part(type="text", text="x" * (mcp_client.MAX_RESULT_CHARS + 500))])
    assert len(long) < mcp_client.MAX_RESULT_CHARS + 100
    assert "已截断" in long


# --------------------------------------------------------------------------- 端到端：登记 → 同步 → 调用

@pytest.fixture
def live_server_row(client, auth_headers, live):
    """登记一个指向本地真实 MCP 服务器的行，用完删掉。"""
    name = "pytest-mcp-live-" + uuid.uuid4().hex[:6]
    res = client.post("/api/v1/mcp-servers", headers=auth_headers, json={
        "name": name, "url": live.url, "transport": "http", "allowed_hosts": ["127.0.0.1"],
    })
    assert res.status_code == 200, res.text
    sid = res.json()["id"]
    try:
        yield {"id": sid, "name": name}
    finally:
        client.delete(f"/api/v1/mcp-servers/{sid}", headers=auth_headers)


def test_test_connection_unreachable_is_502_not_500(client, auth_headers, live_server_row):
    """测试连接打不通的地址：必须是 502 带人话，不能 500 空响应体。

    这是 2026-11-08 修的 P0 的回归防线：SDK 的 CancelledError（BaseException）
    曾经穿透所有 except Exception，最终 FastAPI 回 500 且 body 为空 ——
    页面上只有一个"连接失败"的 toast，用户不知道该改地址还是改凭据。
    """
    res = client.post("/api/v1/mcp-servers/test", headers=auth_headers, json={
        "name": "probe", "url": "http://127.0.0.1:1/mcp", "transport": "http",
        "allowed_hosts": ["127.0.0.1"],
    })
    # 先验负向：连不上必须是 502 带原因，不能 500 空响应体
    assert res.status_code == 502, res.text
    assert "连不上" in res.text


def test_test_connection_reuses_stored_secret(client, auth_headers, live_server_row):
    """编辑已有服务器且没重填凭据时，测试连接要能找回已存的凭据（不用重复输入）。"""
    res = client.post("/api/v1/mcp-servers/test", headers=auth_headers, json={
        "name": live_server_row["name"], "url": mcp_client_hint_url(live_server_row),
        "transport": "http", "allowed_hosts": ["127.0.0.1"],
        "server_id": live_server_row["id"],
    })
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True


def _tool_row(tool_id: int) -> Tool:
    """按 id 取工具行：executor 要 ORM 对象，不是 dict。独立 session 取完就关。"""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        return db.get(Tool, tool_id)
    finally:
        db.close()


def mcp_client_hint_url(row) -> str:
    """从库里取该服务器登记的真实地址（测试不硬编码端口）。"""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        return db.get(McpServer, row["id"]).url
    finally:
        db.close()


def test_sync_then_execute_real_tool(client, auth_headers, live, live_server_row):
    """完整闭环：同步真实工具 → 启用 → 经工具页测试接口真调一次 → 拿到远端返回值。

    这是唯一一条把「同步产物」和「执行」连起来跑的用例。之前两者都各自被打桩，
    同步出来的参数声明到底能不能支撑一次真实调用，没有任何证据。
    """
    res = client.post(f"/api/v1/mcp-servers/{live_server_row['id']}/sync", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 4, res.text   # echo / add / tags / boom

    detail = client.get(f"/api/v1/mcp-servers/{live_server_row['id']}", headers=auth_headers).json()
    by_remote = {t["remote_name"]: t for t in detail["tools"]}
    assert set(by_remote) == {"echo", "add", "tags", "boom"}
    assert all(not t["is_enabled"] for t in detail["tools"]), "同步出来的工具必须默认停用"

    echo_id = by_remote["echo"]["id"]
    client.post(f"/api/v1/tools/{echo_id}/toggle", headers=auth_headers)

    # 经工具页的测试接口真调一次（走完整的闸门 + 执行分支 + 真实 HTTP）
    called = client.post(f"/api/v1/tools/{echo_id}/test", headers=auth_headers, json={"args": {"text": "真实调用"}})
    assert called.status_code == 200, called.text
    assert called.json()["data"]["result"] == {"result": "echo:真实调用"}


def test_sync_downgrades_and_restores_array_param(client, auth_headers, live, live_server_row):
    """数组参数：同步时降级成文本，调用时还原成数组，远端真的收到数组。

    远端 tags 工具签名是 list[str]，如果还原没生效，远端会收到字符串并报错。
    这条用例是"降级 + 还原"闭环的唯一真实证据。
    """
    client.post(f"/api/v1/mcp-servers/{live_server_row['id']}/sync", headers=auth_headers)
    detail = client.get(f"/api/v1/mcp-servers/{live_server_row['id']}", headers=auth_headers).json()
    tags_tool = {t["remote_name"]: t for t in detail["tools"]}["tags"]

    tool = _tool_row(tags_tool["id"])
    # 同步时数组被降级成 string
    params = tool.config["parameters"]
    assert params["properties"]["tags"]["type"] == "string"
    assert "tags" in tool.config["degraded_params"]
    assert "JSON 字符串" in params["properties"]["tags"]["description"]

    client.post(f"/api/v1/tools/{tags_tool['id']}/toggle", headers=auth_headers)
    called = client.post(f"/api/v1/tools/{tags_tool['id']}/test", headers=auth_headers,
                         json={"args": {"tags": '["x", "y"]'}})
    assert called.status_code == 200, called.text
    # 远端返回 "x,y" 说明它收到的是真数组；收到字符串会报类型错
    assert called.json()["data"]["result"] == {"result": "x,y"}


def test_remote_tool_failure_surfaces_as_tool_error(client, auth_headers, live, live_server_row):
    """远端工具自己失败时，测试调用返回的是工具级 error（不是 500）。"""
    client.post(f"/api/v1/mcp-servers/{live_server_row['id']}/sync", headers=auth_headers)
    detail = client.get(f"/api/v1/mcp-servers/{live_server_row['id']}", headers=auth_headers).json()
    boom_id = {t["remote_name"]: t for t in detail["tools"]}["boom"]["id"]
    client.post(f"/api/v1/tools/{boom_id}/toggle", headers=auth_headers)

    res = client.post(f"/api/v1/tools/{boom_id}/test", headers=auth_headers, json={"args": {}})
    assert res.status_code == 200, res.text
    # 工具页测试接口把执行结果放在 data.result 里，成功时是 {"result": ...}、失败时是 {"error": ...}
    assert "error" in res.json()["data"]["result"]


def test_toggle_off_disables_synced_tools(client, auth_headers, live, live_server_row):
    """停用服务器要级联停用它同步出的全部工具。

    这是静默失效类逻辑：漏了的话服务器显示"已停用"，但它的工具仍对模型可见、
    仍能发起调用（地址和凭据都在服务器行上，停用本该即失效）。
    """
    client.post(f"/api/v1/mcp-servers/{live_server_row['id']}/sync", headers=auth_headers)
    detail = client.get(f"/api/v1/mcp-servers/{live_server_row['id']}", headers=auth_headers).json()
    tool_ids = [t["id"] for t in detail["tools"]]

    # 全部启用，再停用服务器。
    # 断言只看本服务器这四个工具的开关状态，不去比"全库 type=mcp 的启用集合" ——
    # 那个集合受其他用例残留影响（共享开发库），一起跑就会假失败。
    for tid in tool_ids:
        client.post(f"/api/v1/tools/{tid}/toggle", headers=auth_headers)
    detail2 = client.get(f"/api/v1/mcp-servers/{live_server_row['id']}", headers=auth_headers).json()
    assert all(t["is_enabled"] for t in detail2["tools"]), "前置条件：四个工具都应已启用"

    client.post(f"/api/v1/mcp-servers/{live_server_row['id']}/toggle", headers=auth_headers)

    for tid in tool_ids:
        row = client.get(f"/api/v1/tools/{tid}", headers=auth_headers)
        if row.status_code == 200:
            assert row.json()["is_enabled"] is False, f"工具 {tid} 应被级联停用"


def test_batch_actions_on_servers(client, auth_headers, live, live_server_row):
    """批量启用 / 停用 / 删除：逐条独立执行并返回成功清单。"""
    res = client.post("/api/v1/mcp-servers/batch", headers=auth_headers,
                      json={"ids": [live_server_row["id"]], "action": "disable"})
    assert res.status_code == 200, res.text
    assert live_server_row["id"] in res.json()["succeeded"]

    res = client.post("/api/v1/mcp-servers/batch", headers=auth_headers,
                      json={"ids": [live_server_row["id"]], "action": "enable"})
    assert res.status_code == 200, res.text
    assert live_server_row["id"] in res.json()["succeeded"]


def test_execute_tool_end_to_end_without_http_layer(client, auth_headers, live, live_server_row):
    """直接走 executor：验证 type='mcp' 分支在真实远端上端到端可用（不经 HTTP 路由）。"""
    client.post(f"/api/v1/mcp-servers/{live_server_row['id']}/sync", headers=auth_headers)
    detail = client.get(f"/api/v1/mcp-servers/{live_server_row['id']}", headers=auth_headers).json()
    add_id = {t["remote_name"]: t for t in detail["tools"]}["add"]["id"]
    client.post(f"/api/v1/tools/{add_id}/toggle", headers=auth_headers)

    tool = _tool_row(add_id)
    assert tool.type == "mcp"
    result = asyncio.run(executor.execute_tool(tool, {"a": 2, "b": 40}, ToolCallContext(tool=tool, source="chat")))
    assert result == {"result": "42"}
