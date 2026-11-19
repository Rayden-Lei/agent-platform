"""内置工具执行器（tools/executor.py）的计算器限额与参数注入。

为什么单独测：
1. **计算器是 DoS 入口**：它挂在每个智能体上，任何能对话的人都能诱导模型调用。
   9**9**9 这类大整数运算在一次字节码里完成且持有 GIL，能让整个后端停摆（2026-09-25 定下的上限）。
   上限的每条边界都必须有断言 —— 放宽一条就是一次可远程触发的宕机。
2. **参数注入是配置生效的唯一通路**：config / api_key 由执行器按签名注入、不走模型输入。
   注错了（比如把密钥当普通参数让模型填）就是凭据泄漏。

不发真实网络请求：HTTP / MCP 分支只测"没有 URL""凭据解不开"这类本地判断。
"""
from __future__ import annotations

import pytest

from app.db.models import Tool
from app.tools import executor


# --------------------------------------------------------------------------- 计算器限额

@pytest.mark.anyio
@pytest.mark.parametrize("expr,expected", [
    ("1+2", 3),
    ("2 * 3", 6),
    ("7 / 2", 3.5),
    ("2 ** 10", 1024),
    ("-5", -5),
    ("+5", 5),
    ("(1 + 2) * 3", 9),
    ("1.5 + 2.5", 4.0),
])
def test_calculator_legal_expressions(expr, expected):
    r = __import__("asyncio").get_event_loop_policy().new_event_loop().run_until_complete(
        executor._execute_builtin("calculator", {"expression": expr}))
    assert r["result"] == expected


@pytest.mark.anyio
async def test_calculator_rejects_oversize_expression():
    """超长表达式挡在 ast.parse 之前：深嵌套括号会让解析器递归过深。"""
    r = await executor._execute_builtin("calculator", {"expression": "1+" * 150 + "1"})
    assert "表达式过长" in r["error"]


@pytest.mark.anyio
async def test_calculator_rejects_huge_exponent():
    """9**9**9 是最典型的拖死后端写法：指数上限必须真的拦住。"""
    r = await executor._execute_builtin("calculator", {"expression": "9**9**9"})
    assert "指数过大" in r["error"]


@pytest.mark.anyio
async def test_calculator_rejects_huge_result():
    """底数与指数都合规、但结果位数超限：按"底数位数 × 指数"先估再算，不算完再判断。

    底数取 400 位、指数取 8：单看都合规（指数远低于 1000），乘起来 3200 位已超 1024 位上限。
    """
    r = await executor._execute_builtin("calculator", {"expression": "9" * 400 + "**8"})
    assert "结果过大" in r["error"] or "表达式过长" in r["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("expr", [
    "'a' * 10",          # 字符串重复能吃掉大量内存
    "().__class__",      # 属性访问 = 对象图入口
    "__import__('os')",
    "[1,2]",
    "1 if 1 else 2",
])
async def test_calculator_rejects_non_arithmetic(expr):
    """计算器只认数字与 + - * / **：其余一律拒（它比条件表达式的求值器更窄）。"""
    r = await executor._execute_builtin("calculator", {"expression": expr})
    assert "error" in r


@pytest.mark.anyio
async def test_calculator_division_by_zero_is_a_tool_error():
    """除零是使用者笔误，要回成工具错误让模型自己纠正，不能抛到运行层。"""
    r = await executor._execute_builtin("calculator", {"expression": "1/0"})
    assert "error" in r


# --------------------------------------------------------------------------- 参数注入

def _tool(**kw) -> Tool:
    """内存里的工具行：这两个分支只读属性、不查库。"""
    return Tool(name=kw.get("name", "http_request"), description="", type=kw.get("type", "builtin"),
                config=kw.get("config", {}), timeout=kw.get("timeout", 30),
                secret_enc=kw.get("secret_enc"))


@pytest.mark.anyio
async def test_call_general_injects_config_from_tool():
    """config 必须来自工具行：配置属于工具不属于系统，注错就等于两个工具共用一份配置。"""
    captured = {}

    async def _fn(url: str = "", *, config: dict | None = None) -> dict:
        captured["config"] = config
        return {"ok": True}

    tool = _tool(config={"timeout": 7})
    await executor._call_general((_fn, True), {}, tool=tool)
    assert captured["config"] == {"timeout": 7}


@pytest.mark.anyio
async def test_call_general_config_defaults_to_empty_without_tool():
    captured = {}

    async def _fn(*, config: dict | None = None) -> dict:
        captured["config"] = config
        return {}

    await executor._call_general((_fn, True), {}, tool=None)
    assert captured["config"] == {}


@pytest.mark.anyio
async def test_call_general_decrypts_api_key_from_tool():
    """密钥从 secret_enc 解密后注入：模型输入里永远拿不到它。"""
    from app.core.security import encrypt_secret

    captured = {}

    async def _fn(query: str = "", *, api_key: str = "") -> dict:
        captured["api_key"] = api_key
        return {}

    tool = _tool(name="web_search", secret_enc=encrypt_secret("sk-injected"))
    await executor._call_general((_fn, True), {"query": "q"}, tool=tool)
    assert captured["api_key"] == "sk-injected"


@pytest.mark.anyio
async def test_call_general_api_key_empty_when_absent():
    captured = {}

    async def _fn(*, api_key: str = "") -> dict:
        captured["api_key"] = api_key
        return {}

    await executor._call_general((_fn, True), {}, tool=_tool())
    assert captured["api_key"] == ""


@pytest.mark.anyio
async def test_call_general_ignores_extra_args():
    """模型多传一个字段不该报 TypeError：多余的键丢掉，缺的用默认值。"""
    async def _fn(text: str = "d") -> dict:
        return {"text": text}

    assert await executor._call_general((_fn, True), {"text": "x", "bogus": 1}) == {"text": "x"}


@pytest.mark.anyio
async def test_call_general_reports_missing_required_arg():
    """缺必填参数要明确说是哪个参数，模型才能补。"""
    async def _fn(text: str) -> dict:
        return {}

    r = await executor._call_general((_fn, True), {})
    assert "缺少必填参数：text" in r["error"]


@pytest.mark.anyio
async def test_call_general_supports_sync_handlers():
    """同步实现也要能调（general.py 里 web_search 就是同步的）。"""
    def _fn(text: str = "") -> dict:
        return {"text": text}

    assert await executor._call_general((_fn, False), {"text": "s"}) == {"text": "s"}


@pytest.mark.anyio
async def test_unknown_builtin_reports_name():
    r = await executor._execute_builtin("no_such_tool", {})
    assert "unknown builtin tool: no_such_tool" in r["error"]


@pytest.mark.anyio
async def test_current_time_is_iso():
    r = await executor._execute_builtin("current_time", {})
    assert "T" in r["result"]


# --------------------------------------------------------------------------- HTTP 工具本地判断

@pytest.mark.anyio
async def test_http_tool_without_url_returns_error():
    """没配 URL 是配置缺失，要回成工具错误而不是抛 KeyError。"""
    tool = _tool(type="http", config={})
    r = await executor._execute_http(tool, {})
    assert "未配置 URL" in r["error"]


@pytest.mark.anyio
async def test_http_tool_with_broken_credentials_reports_it():
    """凭据解不开（AES_KEY 换过）要说清"去工具页重填"，不能只说解密失败。

    密文在 tool.secret_enc 上（不在 auth 里），auth 只描述鉴权方式。
    """
    tool = _tool(type="http", config={"url": "https://example.test/x", "method": "GET"},
                 secret_enc="not-a-valid-ciphertext")
    tool.auth = {"type": "bearer"}
    r = await executor._execute_http(tool, {})
    assert "重新填写凭据" in r["error"]
