"""能力型内置工具的**执行分支**：http_request 的出站与错误处理、web_search 的协议解析。

与 test_general_tools.py 的分工：那个文件测纯函数与 SSRF 拦截（工具调不通的那几条），
这里测"真的发出请求之后"的每一条分支 —— 状态码、超时、非 JSON、Pages 的两种历史形态、
配置缺项、截断。全部用 httpx.MockTransport，不发真实网络请求。

为什么值得单独测：这两条路径的错误处理是给**模型**看的（返回值进上下文），
写错一个字（比如把超时当成功返回）模型就会基于错的信息继续编。
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.tools import general

_REAL_SYNC = httpx.Client


def _mock_sync(monkeypatch, handler):
    """替换 general 里同步用的 httpx.Client（web_search 走 http_util.sync_client）。

    handler 可以返回 Response，也可以返回一个异常实例表示"传输层失败"——
    直接 raise 会被 httpx 当成 handler 自身崩了，与"网络错误"不是一回事。
    """
    seen: list[httpx.Request] = []

    def _wrap(request):
        seen.append(request)
        result = handler(request)
        if isinstance(result, Exception):
            raise result
        return result

    def _factory(*args, **kwargs):
        kwargs.pop("trust_env", None)
        return _REAL_SYNC(transport=httpx.MockTransport(_wrap), **kwargs)

    monkeypatch.setattr(general.http_util.httpx, "Client", _factory)
    return seen


def _mock_async_outbound(monkeypatch, handler):
    """替换 outbound.arequest_with_checked_redirects：http_request 的实际出口。"""
    seen: list[dict] = []

    async def _fake(url, *, allowed=None, method="GET", timeout=None, headers=None, content=None):
        seen.append({"url": url, "allowed": allowed, "method": method, "timeout": timeout,
                     "headers": headers, "content": content})
        result = handler(url)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(general.outbound, "arequest_with_checked_redirects", _fake)
    return seen


# --------------------------------------------------------------------------- http_request

@pytest.mark.anyio
async def test_http_request_rejects_empty_url():
    assert "url 不能为空" in (await general.http_request("  "))["error"]


@pytest.mark.anyio
async def test_http_request_rejects_bad_headers_json(monkeypatch):
    _mock_async_outbound(monkeypatch, lambda url: httpx.Response(200))
    r = await general.http_request("https://example.com/", headers="{not json}")
    assert "headers 必须是 JSON 对象字符串" in r["error"]


@pytest.mark.anyio
async def test_http_request_rejects_headers_not_object(monkeypatch):
    """headers 是 JSON 但不是对象（如数组）：要明确拒，不能悄悄当空头发出去。"""
    _mock_async_outbound(monkeypatch, lambda url: httpx.Response(200))
    r = await general.http_request("https://example.com/", headers="[1,2]")
    assert "headers 必须是 JSON 对象" in r["error"]


@pytest.mark.anyio
async def test_http_request_rejects_unsupported_method(monkeypatch):
    _mock_async_outbound(monkeypatch, lambda url: httpx.Response(200))
    r = await general.http_request("https://example.com/", method="TRACE")
    assert "不支持的方法" in r["error"]


@pytest.mark.anyio
async def test_http_request_passes_method_headers_body(monkeypatch):
    """请求要素要真的传下去：模型写的 body/headers 没送到，等于这个工具没实现。"""
    seen = _mock_async_outbound(monkeypatch, lambda url: httpx.Response(201, json={"ok": 1}))
    r = await general.http_request("https://example.com/api", method="post",
                                   headers='{"X-A": "1"}', body='{"q": 2}')
    assert seen[0]["method"] == "POST"
    assert seen[0]["headers"] == {"X-A": "1"}
    assert seen[0]["content"] == '{"q": 2}'
    assert r["status"] == 201


@pytest.mark.anyio
async def test_http_request_truncates_large_body(monkeypatch):
    """响应体超上限要截断并标注：不截断一个 10MB 的页面会直接撑爆模型上下文。"""
    _mock_async_outbound(monkeypatch, lambda url: httpx.Response(
        200, content=b"x" * 5000, headers={"content-type": "text/plain"}))
    r = await general.http_request("https://example.com/", config={"max_bytes": 100})
    assert len(r["body"]) == 100
    assert r["truncated"] is True


@pytest.mark.anyio
async def test_http_request_not_truncated_when_small(monkeypatch):
    _mock_async_outbound(monkeypatch, lambda url: httpx.Response(200, content=b"tiny"))
    r = await general.http_request("https://example.com/")
    assert r["body"] == "tiny" and r["truncated"] is False


@pytest.mark.anyio
async def test_http_request_maps_timeout(monkeypatch):
    _mock_async_outbound(monkeypatch, lambda url: httpx.TimeoutException("slow"))
    r = await general.http_request("https://example.com/", config={"timeout": 5})
    assert "请求超时" in r["error"] and "5s" in r["error"]


@pytest.mark.anyio
async def test_http_request_maps_transport_error(monkeypatch):
    _mock_async_outbound(monkeypatch, lambda url: httpx.ConnectError("refused"))
    r = await general.http_request("https://example.com/")
    assert "请求失败" in r["error"] and "ConnectError" in r["error"]


@pytest.mark.anyio
async def test_http_request_maps_redirect_blocked(monkeypatch):
    """重定向被出站闸门拦下：要作为工具错误回给模型，而不是让异常冒到运行层。"""
    _mock_async_outbound(monkeypatch, lambda url: general.outbound.OutboundBlocked("跳到内网了"))
    r = await general.http_request("https://example.com/")
    assert "跳到内网了" in r["error"]


@pytest.mark.anyio
async def test_http_request_passes_allowed_hosts_to_outbound(monkeypatch):
    """工具自己配的白名单要传给闸门（而不是只在这里判一次就完事）。

    _host_allowed 会先做一次 DNS 解析（防 DNS 重绑定），用例不该依赖外网可达，
    所以把解析这一步打桩掉，只验"配了白名单之后有没有原样传给闸门"。
    """
    monkeypatch.setattr(general.outbound, "check_host", lambda host, allow=None: None)
    seen = _mock_async_outbound(monkeypatch, lambda url: httpx.Response(200))
    await general.http_request("https://api.example.com/", config={"allowed_hosts": "api.example.com, *.ok.com"})
    assert seen[0]["allowed"] == ["api.example.com", "*.ok.com"]


@pytest.mark.anyio
async def test_http_request_empty_whitelist_means_no_whitelist(monkeypatch):
    """白名单为空时传 None（只拦内网、放行公网），不是传空列表（空列表 = 全拒）。"""
    seen = _mock_async_outbound(monkeypatch, lambda url: httpx.Response(200))
    await general.http_request("https://example.com/", config={})
    assert seen[0]["allowed"] is None


@pytest.mark.anyio
async def test_http_request_decodes_unknown_charset(monkeypatch):
    """响应头声明的编码不认识时退回 utf-8，不能因为编码名写错就整条失败。"""
    _mock_async_outbound(monkeypatch, lambda url: httpx.Response(
        200, content="中文".encode("utf-8"), headers={"content-type": "text/plain; charset=x-unknown"}))
    r = await general.http_request("https://example.com/")
    assert "中文" in r["body"]


@pytest.mark.anyio
async def test_http_request_limits_header_count(monkeypatch):
    """响应头只留前 30 个：有些站点回几十个 Set-Cookie，全塞进上下文没有意义。"""
    headers = {f"X-H{i}": "v" for i in range(60)}
    _mock_async_outbound(monkeypatch, lambda url: httpx.Response(200, headers=headers))
    r = await general.http_request("https://example.com/")
    assert len(r["headers"]) <= 30


# --------------------------------------------------------------------------- web_search

def _search_response(pages, **extra):
    body = {"Response": {"Pages": pages, **extra}}
    return httpx.Response(200, json=body)


def test_web_search_requires_api_key():
    r = general.web_search("q", api_key="")
    assert "未配置 API Key" in r["error"]


def test_web_search_rejects_empty_query():
    assert "query 不能为空" in general.web_search("   ", api_key="k")["error"]


def test_web_search_rejects_overlong_query():
    assert "关键词过长" in general.web_search("x" * 2001, api_key="k")["error"]


def test_web_search_empty_endpoint_falls_back_to_default(monkeypatch):
    """endpoint 配成空串时**回落到默认地址**而不是报错：tool_config 把空串当"没配"，
    与"管理员显式关掉这个工具"是两回事（后者该用 is_enabled）。"""
    seen = _mock_sync(monkeypatch, lambda req: _search_response([]))
    general.web_search("q", api_key="k", config={"endpoint": ""})
    assert str(seen[0].url).startswith("https://api.wsa.cloud.tencent.com/SearchPro")


def test_web_search_parses_results(monkeypatch):
    _mock_sync(monkeypatch, lambda req: _search_response([
        {"title": "T1", "url": "https://a", "site": "A", "date": "2026", "score": 0.9, "passage": "P1"},
    ]))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert r["count"] == 1
    assert r["results"][0] == {"title": "T1", "url": "https://a", "site": "A", "date": "2026",
                               "score": 0.9, "passage": "P1"}


def test_web_search_sends_bearer_and_query(monkeypatch):
    seen = _mock_sync(monkeypatch, lambda req: _search_response([]))
    general.web_search("关键词", api_key="secret-key", config={"endpoint": "https://search.test/SearchPro"})
    assert seen[0].headers["authorization"] == "Bearer secret-key"
    assert json.loads(seen[0].content)["Query"] == "关键词"


def test_web_search_accepts_json_string_pages(monkeypatch):
    """Pages 元素历史上是"JSON 字符串套 JSON"：两种形态都要认，否则升级 SDK 后静默全空。"""
    _mock_sync(monkeypatch, lambda req: _search_response([
        json.dumps({"title": "T", "url": "https://a", "passage": "P"}),
    ]))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert r["count"] == 1 and r["results"][0]["title"] == "T"


def test_web_search_skips_unparsable_page_items(monkeypatch):
    """单条坏数据跳过，不让整次搜索失败。"""
    _mock_sync(monkeypatch, lambda req: _search_response([
        "{broken", 123, None, {"title": "good", "url": "https://a"},
    ]))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert r["count"] == 1 and r["results"][0]["title"] == "good"


def test_web_search_truncates_passage(monkeypatch):
    """passage 截到 500 字：搜索结果进上下文，不截断几条就能占满窗口。"""
    _mock_sync(monkeypatch, lambda req: _search_response([{"title": "T", "passage": "x" * 2000}]))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert len(r["results"][0]["passage"]) == 500


def test_web_search_respects_limit(monkeypatch):
    """limit 传了就按它截；超出 max_limit 时按 max_limit 收。"""
    pages = [{"title": f"T{i}", "url": f"https://{i}"} for i in range(10)]
    _mock_sync(monkeypatch, lambda req: _search_response(pages))
    conf = {"endpoint": "https://search.test/SearchPro", "max_limit": 3, "default_limit": 2}
    assert general.web_search("q", api_key="k", config=conf)["count"] == 2
    assert general.web_search("q", limit=99, api_key="k", config=conf)["count"] == 3


def test_web_search_maps_http_status(monkeypatch):
    _mock_sync(monkeypatch, lambda req: httpx.Response(502, text="bad gateway"))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert "HTTP 502" in r["error"]


def test_web_search_maps_non_json(monkeypatch):
    _mock_sync(monkeypatch, lambda req: httpx.Response(200, text="<html>"))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert "不是 JSON" in r["error"]


def test_web_search_maps_timeout(monkeypatch):
    _mock_sync(monkeypatch, lambda req: httpx.TimeoutException("slow"))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro", "timeout": 7})
    assert "搜索超时" in r["error"]


def test_web_search_maps_transport_error(monkeypatch):
    _mock_sync(monkeypatch, lambda req: httpx.ConnectError("refused"))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert "搜索请求失败" in r["error"]


def test_web_search_surfaces_api_error(monkeypatch):
    """搜索服务自己在 body 里报错（HTTP 200 + Error 字段）：要原样带给模型看。"""
    _mock_sync(monkeypatch, lambda req: httpx.Response(
        200, json={"Response": {"Error": {"Code": "AuthFailure", "Message": "bad key"}}}))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert "AuthFailure" in r["error"] and "bad key" in r["error"]


def test_web_search_requires_pages_field(monkeypatch):
    _mock_sync(monkeypatch, lambda req: httpx.Response(200, json={"Response": {}}))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert "没有返回 Pages" in r["error"]


def test_web_search_accepts_flat_body(monkeypatch):
    """有的兼容实现不回 Response 包装层，直接把 Pages 放在顶层。"""
    _mock_sync(monkeypatch, lambda req: httpx.Response(200, json={"Pages": [{"title": "T"}]}))
    r = general.web_search("q", api_key="k", config={"endpoint": "https://search.test/SearchPro"})
    assert r["count"] == 1


# --------------------------------------------------------------------------- 配置收敛

@pytest.mark.parametrize("raw,expected", [
    ("30", 30), (30, 30), (30.9, 30), ("abc", None), (None, None), ([], None),
])
def test_as_int_converges(raw, expected):
    """配置存的是页面写下的字符串，历史行里还有数字：两种都要认，坏值返回 None 交给兜底。"""
    assert general._as_int(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("1.5", 1.5), (2, 2.0), ("x", None), (None, None),
])
def test_as_float_converges(raw, expected):
    assert general._as_float(raw) == expected


def test_tool_config_int_falls_back_on_garbage(caplog):
    """坏配置不能抛异常：请求路径上抛 TypeError 会让整次工具调用 500。"""
    assert general.tool_config_int("http_request", {"timeout": "abc"}, "timeout") == 20
    assert "不是整数" in caplog.text


def test_tool_config_str_stringifies_non_string():
    assert general.tool_config_str("http_request", {"allowed_hosts": 123}, "allowed_hosts") == "123"


def test_pattern_matches_delegates_to_outbound():
    """白名单匹配只有一处实现：这里再写一份就会和工具行闸门口径分叉。"""
    assert general._pattern_matches("api.example.com", "api.example.com")
    assert not general._pattern_matches("evil.com", "api.example.com")
