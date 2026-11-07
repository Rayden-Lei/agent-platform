"""模型调用全量日志（2026-11-08）：打码、截断、响应解析、路由。

这张表存在的意义就是"排查时能看到原始报文"，所以测试的重点不是"能写进去"，
而是**该看的都还在、不该看的确实被打码了**。
"""
from __future__ import annotations

import json

import pytest

from app.db.models import LlmCall
from app.db.session import SessionLocal
from app.model_gateway import llm_log
from app.services import llm_log_service


# --------------------------------------------------------------------------- 打码：只打凭据

def test_mask_url_keeps_address_but_hides_key():
    """地址本身要能看见（排查打到了哪个上游），只有 key 参数打码。"""
    masked = llm_log.mask_url("https://api.example.com/v1/chat/completions?key=sk-secret&stream=true")
    assert "api.example.com" in masked
    assert "/v1/chat/completions" in masked
    assert "sk-secret" not in masked
    assert "key=***" in masked
    assert "stream=true" in masked


def test_mask_url_without_key_is_untouched():
    url = "https://api.example.com/v1/chat/completions"
    assert llm_log.mask_url(url) == url


def test_mask_headers_hides_only_secret_headers():
    """请求头里凭据打码，其余（Content-Type 等）保留 —— 后者也是排查依据。"""
    out = llm_log.mask_headers({
        "Authorization": "Bearer sk-x", "api-key": "sk-y",
        "Content-Type": "application/json", "X-Trace": "abc",
    })
    assert out["Authorization"] == "***"
    assert out["api-key"] == "***"
    assert out["Content-Type"] == "application/json"
    assert out["X-Trace"] == "abc"


def test_mask_body_keeps_messages_and_tools_but_hides_keys():
    """请求体里 messages 全文、tools 定义、temperature 都必须原样保留。"""
    body = {
        "model": "gpt-x", "temperature": 0.7, "api_key": "sk-leak",
        "messages": [{"role": "system", "content": "你是助手"}, {"role": "user", "content": "你好"}],
        "tools": [{"type": "function", "function": {"name": "f", "description": "d"}}],
    }
    masked = llm_log.mask_body(body)
    assert masked["api_key"] == "***"
    assert masked["temperature"] == 0.7
    assert masked["messages"][0]["content"] == "你是助手"
    assert masked["messages"][1]["content"] == "你好"
    assert masked["tools"][0]["function"]["name"] == "f"
    assert masked["model"] == "gpt-x"


def test_mask_body_walks_nested_structures():
    """嵌套的 list / dict 里的凭据也要打码，不能只打顶层。"""
    body = {"a": [{"nested": {"access_token": "t0k3n", "keep": "v"}}]}
    masked = llm_log.mask_body(body)
    assert masked["a"][0]["nested"]["access_token"] == "***"
    assert masked["a"][0]["nested"]["keep"] == "v"


# --------------------------------------------------------------------------- 截断：看得见的不完整

def test_clamp_text_keeps_short_text_intact():
    text, truncated = llm_log.clamp_text("短文本", limit=100)
    assert text == "短文本"
    assert truncated is False


def test_clamp_text_marks_length_when_truncated():
    """截断时必须注明原文长度 —— 让人知道"这里不完整"，而不是以为报文就这么短。"""
    text, truncated = llm_log.clamp_text("x" * 500, limit=100)
    assert truncated is True
    assert text.startswith("x" * 100)
    assert "已截断" in text
    assert "500" in text


def test_clamp_obj_keeps_small_object():
    obj = {"a": 1, "b": [1, 2, 3]}
    out, truncated = llm_log.clamp_obj(obj, limit=1000)
    assert out == obj
    assert truncated is False


def test_clamp_obj_degrades_large_object_with_preview():
    """超大请求体退化成带预览的说明，仍然能看到开头。"""
    out, truncated = llm_log.clamp_obj({"messages": [{"content": "y" * 500}]}, limit=200)
    assert truncated is True
    assert isinstance(out, dict)
    assert out["_truncated"] is True
    assert out["_original_chars"] > 200
    assert "y" in out["_preview"]


# --------------------------------------------------------------------------- 响应解析

def test_extract_from_sse_collects_content_reasoning_and_tools():
    """流式响应是一串 data: 帧，正文 / 思考过程 / 工具调用参数都要拼对。"""
    frames = [
        {"choices": [{"delta": {"reasoning_content": "先想一下"}}]},
        {"choices": [{"delta": {"content": "你好"}}]},
        {"choices": [{"delta": {"content": "，世界"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "get_weather", "arguments": '{"ci'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ty": "北京"}'}}]}}]},
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
    ]
    text = "\n\n".join("data: " + json.dumps(f) for f in frames) + "\n\ndata: [DONE]\n"
    out = llm_log.extract_from_response(text)
    assert out["content"] == "你好，世界"
    assert out["reasoning"] == "先想一下"
    assert out["tool_calls"] == [{"name": "get_weather", "arguments": {"city": "北京"}}]
    assert out["usage"]["prompt_tokens"] == 10


def test_extract_from_non_stream_response():
    """非流式响应（message 而不是 delta）也要认。"""
    payload = {"choices": [{"message": {"content": "答案是 42"}}],
               "usage": {"prompt_tokens": 3, "completion_tokens": 7}}
    out = llm_log.extract_from_response(json.dumps(payload))
    assert out["content"] == "答案是 42"
    assert out["usage"]["completion_tokens"] == 7


def test_extract_survives_garbage_response():
    """对方返回的不是 JSON / SSE（比如一整页 HTML 错误页）时不能崩，返回空但原文仍会保存。"""
    out = llm_log.extract_from_response("<html><body>502 Bad Gateway</body></html>")
    assert out["content"] == ""
    assert out["tool_calls"] == []


def test_extract_keeps_unparseable_tool_arguments():
    """模型拼出的参数不是合法 JSON 时原样保留 —— 这是排查"为什么工具调用失败"的关键证据。"""
    frames = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "f", "arguments": '{bad json'}}]}}]}]
    text = "data: " + json.dumps(frames[0])
    out = llm_log.extract_from_response(text)
    assert out["tool_calls"][0]["arguments"] == "{bad json"


def test_extract_from_empty():
    assert llm_log.extract_from_response(None)["content"] == ""
    assert llm_log.extract_from_response("")["content"] == ""


# --------------------------------------------------------------------------- 工具定义提取

def test_summarize_tools_keeps_name_description_and_schema():
    """"给了模型什么工具"必须带参数声明：排查"模型为什么没传某参数"要看声明长什么样。"""
    body = {"tools": [
        {"type": "function", "function": {
            "name": "search", "description": "搜索",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
        }},
    ]}
    out = llm_log.summarize_tools(body)
    assert out[0]["name"] == "search"
    assert out[0]["description"] == "搜索"
    assert out[0]["parameters"]["required"] == ["q"]


def test_summarize_tools_without_tools():
    assert llm_log.summarize_tools({"model": "x"}) == []
    assert llm_log.summarize_tools(None) == []


def test_summarize_tools_skips_malformed_entries():
    """一条脏数据不该让整个工具清单丢失。"""
    body = {"tools": [{"function": {"name": ""}}, {"function": {"name": "ok"}}, "不是对象"]}
    out = llm_log.summarize_tools(body)
    assert [t["name"] for t in out] == ["ok"]


# --------------------------------------------------------------------------- 落库与查询

@pytest.fixture
def make_call():
    """直接插一条记录（不走真实模型调用，测试只验存储与查询）。"""
    created: list[int] = []

    def _make(**kw):
        db = SessionLocal()
        try:
            row = LlmCall(
                run_id=kw.get("run_id"), model_id=kw.get("model_id"), model_name=kw.get("model_name", "pytest-model"),
                purpose=kw.get("purpose", "chat"), url=kw.get("url", "https://api.example.com/v1/chat/completions"),
                method="POST", request_body=kw.get("request_body", {"messages": [{"role": "user", "content": "hi"}]}),
                response_body=kw.get("response_body", 'data: {"choices":[{"delta":{"content":"ok"}}]}'),
                response_text=kw.get("response_text", "ok"), reasoning_text=kw.get("reasoning_text"),
                tools_offered=kw.get("tools_offered", []), tool_calls=kw.get("tool_calls", []),
                status=kw.get("status", "success"), http_status=kw.get("http_status", 200),
                error=kw.get("error"), prompt_tokens=kw.get("prompt_tokens", 10),
                completion_tokens=kw.get("completion_tokens", 5), duration_ms=kw.get("duration_ms", 100),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            created.append(row.id)
            return row.id
        finally:
            db.close()

    yield _make
    db = SessionLocal()
    try:
        for cid in created:
            obj = db.get(LlmCall, cid)
            if obj is not None:
                db.delete(obj)
        db.commit()
    finally:
        db.close()


def test_list_hides_heavy_fields(client, auth_headers, make_call):
    """列表不返回报文大字段：上百条几 MB 的报文会让页面卡死。"""
    make_call()
    res = client.get("/api/v1/llm-calls", headers=auth_headers, params={"page_size": 5})
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert items
    for item in items:
        assert "request_body" not in item
        assert "response_body" not in item
        # 但摘要信息要在：能看出调了哪些工具、状态、耗时
        assert "tool_names" in item and "called_tools" in item


def test_detail_returns_full_payload(client, auth_headers, make_call):
    """详情要含完整请求体与响应原文 —— 这是这个页面存在的唯一理由。"""
    # tools_offered 在真实链路里由 summarize_tools 从请求体提取；这里直接插行，所以两边都给
    cid = make_call(request_body={"messages": [{"role": "system", "content": "你是助手"}],
                                  "tools": [{"type": "function", "function": {"name": "f"}}]},
                    tools_offered=[{"name": "f", "description": "", "parameters": {}}],
                    response_body='data: {"choices":[{"delta":{"content":"完整回答"}}]}')
    res = client.get(f"/api/v1/llm-calls/{cid}", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    # 完整请求体：系统提示词要能看到
    assert body["request_body"]["messages"][0]["content"] == "你是助手"
    # 完整响应原文：SSE 帧原样保存
    assert "完整回答" in body["response_body"]
    assert body["tools_offered"][0]["name"] == "f"


def test_filter_by_run_id(client, auth_headers, make_call):
    make_call(run_id=777001)
    make_call(run_id=777002)
    res = client.get("/api/v1/llm-calls", headers=auth_headers, params={"run_id": 777001, "page_size": 50})
    assert res.status_code == 200
    assert all(i["run_id"] == 777001 for i in res.json()["items"])
    # 清理
    for i in res.json()["items"]:
        client.delete(f"/api/v1/llm-calls/{i['id']}", headers=auth_headers) if False else None


def test_filter_by_status(client, auth_headers, make_call):
    make_call(status="error", error="HTTP 500")
    res = client.get("/api/v1/llm-calls", headers=auth_headers, params={"status": "error", "page_size": 5})
    assert res.status_code == 200
    assert all(i["status"] == "error" for i in res.json()["items"])


def test_search_matches_url_and_error(client, auth_headers, make_call):
    make_call(url="https://unique-host-pytest.example.com/v1/chat")
    res = client.get("/api/v1/llm-calls", headers=auth_headers,
                     params={"q": "unique-host-pytest", "page_size": 10})
    assert res.status_code == 200
    assert res.json()["total"] >= 1


def test_stats(client, auth_headers, make_call):
    make_call()
    res = client.get("/api/v1/llm-calls/stats", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] >= 1
    assert "failed" in body and "today" in body
    assert body["enabled"] is True


def test_missing_call_is_404(client, auth_headers):
    assert client.get("/api/v1/llm-calls/99999999", headers=auth_headers).status_code == 404


def test_caller_cannot_read_logs(client, caller_headers):
    """调用日志含完整请求体（可能有机密提示词），caller 一律 403。"""
    assert client.get("/api/v1/llm-calls", headers=caller_headers).status_code == 403


def test_time_range_requires_timezone(client, auth_headers):
    """时间区间必须带时区：naive 值与 timestamptz 比较结果取决于会话时区，会静默出错。"""
    res = client.get("/api/v1/llm-calls", headers=auth_headers, params={"start": "2026-01-01T00:00:00"})
    assert res.status_code == 400, res.text


def test_persist_extracts_tools_and_masks_secrets():
    """走真实落库路径（llm_log._persist）：工具定义自动提取、凭据自动打码、报文完整保存。

    这条是整条链路的收口验证 —— 前面各函数单测都对，但接起来忘了调某一环是常见失误。
    """
    rec = llm_log.LlmCallRecorder(purpose="chat", run_id=None, model_id=None, model_name="pytest-persist")
    rec.url = "https://api.example.com/v1/chat/completions?key=sk-should-hide"
    rec.request_body = {
        "model": "m", "temperature": 0.3, "api_key": "sk-should-hide",
        "messages": [{"role": "user", "content": "原始问题全文"}],
        "tools": [{"type": "function", "function": {
            "name": "lookup", "description": "查一下",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        }}],
    }
    rec.http_status = 200
    rec.finish(response_text='data: {"choices":[{"delta":{"content":"回答全文"}}], "usage":{"prompt_tokens":11,"completion_tokens":22}}')

    db = SessionLocal()
    try:
        row = db.query(LlmCall).filter(LlmCall.model_name == "pytest-persist").order_by(LlmCall.id.desc()).first()
        assert row is not None
        # 凭据打码
        assert row.request_body["api_key"] == "***"
        assert "sk-should-hide" not in (row.url or "")
        # 其余全部保留
        assert row.request_body["messages"][0]["content"] == "原始问题全文"
        assert row.request_body["temperature"] == 0.3
        assert row.tools_offered[0]["name"] == "lookup"
        assert row.tools_offered[0]["parameters"]["properties"]["q"]["type"] == "string"
        assert row.response_text == "回答全文"
        assert row.prompt_tokens == 11 and row.completion_tokens == 22
        assert row.status == "success"
        db.delete(row)
        db.commit()
    finally:
        db.close()



def test_recorder_is_isolated_between_concurrent_tasks():
    """采集器必须按上下文隔离，不能按线程。

    对话是异步的：同一个线程里会同时跑多个请求（uvicorn / TestClient 都是）。
    用 threading.local 时两个并发对话会互相覆盖采集器 —— 一边的请求记到另一边头上，
    甚至记成别人的 run_id，排查时看到的是"完全对不上的报文"。
    contextvars 随 asyncio task 复制，天然隔离。
    """
    import asyncio

    async def worker(name: str) -> str | None:
        rec = llm_log.LlmCallRecorder(purpose="chat", model_name=name)
        token = llm_log.bind(rec)
        try:
            await asyncio.sleep(0.01)  # 让出控制权，另一个 task 会在这期间 bind
            got = llm_log.current()
            return got.model_name if got else None
        finally:
            llm_log.unbind(token)

    async def main() -> list[str | None]:
        return await asyncio.gather(worker("a"), worker("b"), worker("c"))

    assert asyncio.run(main()) == ["a", "b", "c"]


def test_unbind_restores_outer_recorder():
    """嵌套调用（一轮对话里再发摘要）收尾时要还原外层采集器，而不是置空。"""
    outer = llm_log.LlmCallRecorder(purpose="chat", model_name="outer")
    outer_token = llm_log.bind(outer)
    try:
        inner = llm_log.LlmCallRecorder(purpose="summary", model_name="inner")
        inner_token = llm_log.bind(inner)
        assert llm_log.current() is inner
        llm_log.unbind(inner_token)
        # 还原成 outer，不是 None —— 否则外层剩下的请求会记不上
        assert llm_log.current() is outer
    finally:
        llm_log.unbind(outer_token)

