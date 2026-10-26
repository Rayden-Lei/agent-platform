"""工具执行闸门（docs/16 P3a）：来源与目标地址的判定。

纯函数与内存对象，不碰数据库与网络。
"""
import asyncio

import pytest

from app.core.exceptions import BizError
from app.db.models import Tool
from app.services.tool_service import _check_allowed_hosts
from app.tools.executor import execute_tool
from app.tools.permission import ToolCallContext, check


def _tool(**kwargs) -> Tool:
    defaults = dict(id=1, name="天气", type="http", is_enabled=True, timeout=10,
                    config={"url": "https://api.example.com/weather", "method": "GET"}, description="")
    defaults.update(kwargs)
    return Tool(**defaults)


def _check(tool: Tool, source: str = "chat"):
    return check(ToolCallContext(tool=tool, source=source, agent_id=2, run_id=3))


def test_disabled_tool_is_denied():
    decision, reason = _check(_tool(is_enabled=False))
    assert decision == "deny" and "已停用" in reason


def test_builtin_tool_is_always_allowed():
    assert _check(_tool(type="builtin", name="calculator", config={}))[0] == "allow"


def test_share_source_cannot_use_http_tools():
    decision, reason = _check(_tool(), source="share")
    assert decision == "deny" and "分享" in reason


def test_admin_test_skips_host_allowlist():
    """管理员在工具页测试时白名单还没填好是常态。"""
    decision, reason = _check(_tool(config={"url": "https://anywhere.example.org/x"}), source="admin_test")
    assert decision == "allow" and reason


def test_allowed_host_match_and_subdomain():
    tool = _tool(config={"url": "https://api.example.com/x", "allowed_hosts": ["api.example.com"]})
    assert _check(tool)[0] == "allow"
    sub = _tool(config={"url": "https://v2.api.example.com/x", "allowed_hosts": ["api.example.com"]})
    assert _check(sub)[0] == "allow"


def test_host_outside_allowlist_is_denied():
    tool = _tool(config={"url": "https://evil.example.net/x", "allowed_hosts": ["api.example.com"]})
    decision, reason = _check(tool)
    assert decision == "deny" and "白名单" in reason
    assert _check(tool, source="workflow")[0] == "deny"


def test_missing_url_with_allowlist_is_denied():
    decision, reason = _check(_tool(config={"allowed_hosts": ["api.example.com"]}))
    assert decision == "deny" and "未配置 URL" in reason


def test_empty_allowlist_allows_with_warning_reason():
    """过渡期：存量工具没有白名单，放行但要能清点出来。"""
    decision, reason = _check(_tool(config={"url": "https://anywhere.example.org/x"}))
    assert decision == "allow" and "allowed_hosts" in reason


def test_denied_call_does_not_reach_network():
    tool = _tool(config={"url": "https://evil.example.net/x", "allowed_hosts": ["api.example.com"]})
    result = asyncio.run(execute_tool(tool, {}, ToolCallContext(tool=tool, source="chat", run_id=9)))
    assert result == {"error": "该工具在当前调用来源下不可用：工具目标地址不在白名单内：evil.example.net", "denied": True}


def test_allowlist_shape_validation():
    _check_allowed_hosts({"allowed_hosts": ["api.example.com"]}, "http")  # 正常不抛
    _check_allowed_hosts({}, "http")
    with pytest.raises(BizError):
        _check_allowed_hosts({"allowed_hosts": ["https://api.example.com"]}, "http")
    with pytest.raises(BizError):
        _check_allowed_hosts({"allowed_hosts": ["api.example.com:8080"]}, "http")
    with pytest.raises(BizError):
        _check_allowed_hosts({"allowed_hosts": ["api.example.com"]}, "builtin")
    with pytest.raises(BizError):
        _check_allowed_hosts({"allowed_hosts": [f"h{i}.example.com" for i in range(21)]}, "http")
