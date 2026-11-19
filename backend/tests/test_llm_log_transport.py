"""模型调用采集的**传输层**（llm_log._RecordingTransport / _StreamTee / wrap_client）。

为什么单独测：其余用例测的是掩码、裁剪、SSE 解析这些纯函数，而真正"把报文抓下来"的是
这两个 httpx 包装类。它们出错的后果都是静默的 —— 日志表里全是空请求体、或流式响应的
正文一个字没记，页面上看起来"这次调用没内容"，排查时完全无从下手。

**收尾由谁负责**：传输层只负责抓（填 url / request_body / http_status，流式还负责边读边攒）；
recorder.finish() 由 gateway 的 guarded_invoke / guarded_ainvoke / guarded_astream 在
finally 里调。所以本文件的非流式用例不自己调 finish —— 断言的是"抓没抓到"，不是"落没落库"。
流式那条是例外：_StreamTee 在流读完或关闭时自己收尾。

不连真实上游：MockTransport 当内层，只验包装层的行为。
"""
from __future__ import annotations

import httpx
import pytest

from app.model_gateway import llm_log


class _Recorder(llm_log.LlmCallRecorder):
    """把落库换成记录调用参数：用例不写库，也能断言"收尾时传了什么"。"""

    def __init__(self, **kw):
        super().__init__(**{"purpose": "chat", "model_name": "pytest-model", **kw})
        self.finished: list[dict] = []

    def finish(self, *, response_text=None, status=None, http_status=None, error=None):
        # 复刻父类的字段赋值（只是把落库换成记录）：用例要断言"采集器上留下了什么"
        if response_text is not None:
            self.response_body = response_text
        if status:
            self.status = status
        if http_status is not None:
            self.http_status = http_status
        if error:
            self.error = error
        self.finished.append({"response_text": response_text, "status": status,
                              "http_status": http_status, "error": error})
        self._recorded = True


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class _SseStream(httpx.AsyncByteStream):
    """真流：按分块产出 SSE 帧。

    **不能用 httpx.Response(200, content=...)**：那样响应会带上 _content 缓存，
    Response.aiter_bytes 直接切片返回，根本不走 stream —— _StreamTee 永远不会被调用，
    用例会误判成"采集没生效"（实际是没走流式路径）。
    """

    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


def _sse(chunks: list[bytes]) -> httpx.Response:
    return httpx.Response(200, stream=_SseStream(chunks),
                          headers={"content-type": "text/event-stream"})


# --------------------------------------------------------------------------- 非流式

@pytest.mark.anyio
async def test_records_request_and_response():
    """请求体按 JSON 解、URL 记下（掩码后）：这是排查"模型为什么这样回答"的唯一依据。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(lambda r: httpx.Response(200, json={"ok": True})), rec)
        async with client:
            resp = await client.post("https://api.test/v1/chat/completions",
                                     json={"model": "m", "messages": [{"role": "user", "content": "q"}]})
            await resp.aread()
    finally:
        llm_log.unbind(token)

    assert rec.method == "POST"
    assert rec.url == "https://api.test/v1/chat/completions"
    assert rec.request_body["messages"][0]["content"] == "q"
    assert rec.http_status == 200


@pytest.mark.anyio
async def test_masks_api_key_in_url():
    """地址里的 key 要打码：日志会被人看、也可能被导出，明文密钥是不可逆的泄漏。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(lambda r: httpx.Response(200, json={})), rec)
        async with client:
            resp = await client.get("https://api.test/v1/models?key=sk-secret-123")
            await resp.aread()
    finally:
        llm_log.unbind(token)

    assert "sk-secret-123" not in rec.url


@pytest.mark.anyio
async def test_unparseable_request_body_is_kept_raw():
    """请求体不是 JSON（比如表单）：存原文，能看见总比看不见好。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(lambda r: httpx.Response(200, json={})), rec)
        async with client:
            resp = await client.post("https://api.test/x", content=b"a=1&b=2",
                                     headers={"content-type": "application/x-www-form-urlencoded"})
            await resp.aread()
    finally:
        llm_log.unbind(token)

    assert rec.request_body == {"_raw": "a=1&b=2"}


@pytest.mark.anyio
async def test_empty_request_body_is_not_recorded():
    """GET 之类的空请求体：留 None，不要存一个空字符串。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(lambda r: httpx.Response(200, json={})), rec)
        async with client:
            resp = await client.get("https://api.test/x")
            await resp.aread()
    finally:
        llm_log.unbind(token)

    assert rec.request_body is None


@pytest.mark.anyio
async def test_transport_error_propagates_and_is_reported():
    """上游连不上：异常要照常往上抛（熔断器靠它计数），同时把错误记下来。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        def handler(request):
            raise httpx.ConnectError("refused")

        client = llm_log.wrap_client(_client(handler), rec)
        async with client:
            with pytest.raises(httpx.ConnectError):
                await client.post("https://api.test/x", json={})
    finally:
        llm_log.unbind(token)

    # 传输层在异常路径上直接把错误记进采集器（并标记已收尾，gateway 的 finally 不会再覆盖）
    assert rec.status == "error"
    assert "ConnectError" in rec.error
    assert rec._recorded is True


@pytest.mark.anyio
async def test_error_http_status_is_recorded_on_the_recorder():
    """4xx/5xx 的 http_status 要落到采集器上：收尾时据此判成功/失败，记错会让失败率永远为 0。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(lambda r: httpx.Response(429, json={"error": "rate"})), rec)
        async with client:
            resp = await client.post("https://api.test/x", json={})
            await resp.aread()
    finally:
        llm_log.unbind(token)

    assert rec.http_status == 429


@pytest.mark.anyio
async def test_client_without_recorder_passes_through():
    """没有绑定采集器时（如后台任务）必须完全透明：不能少发请求或改响应。"""
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    # 记下绑定前的值：unbind 恢复的是**外层**上下文，而外层可能有别人绑的采集器
    # （pytest 用例执行顺序不同，写死断言 None 会在整轮跑到这里时偶然红）
    before = llm_log.current()
    token = llm_log.bind(None)
    try:
        assert llm_log.current() is None, "bind(None) 之后当前上下文应当没有采集器"
        client = llm_log.wrap_client(_client(handler), _Recorder())
        async with client:
            resp = await client.post("https://api.test/x", json={})
            assert resp.json() == {"ok": True}
    finally:
        llm_log.unbind(token)
    assert llm_log.current() is before, "unbind 必须精确还原到绑定前的采集器"


# --------------------------------------------------------------------------- 流式

@pytest.mark.anyio
async def test_stream_body_is_captured_while_passing_through():
    """流式响应必须"边读边攒"：aread() 一次就把流吃掉，调用方拿不到分块。"""
    chunks = [b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n',
              b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n']
    sse = b"".join(chunks)
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(lambda r: _sse(chunks)), rec)
        seen = []
        async with client:
            async with client.stream("POST", "https://api.test/x", json={}) as resp:
                async for chunk in resp.aiter_bytes():
                    seen.append(chunk)
    finally:
        llm_log.unbind(token)

    assert b"".join(seen) == sse, "分块必须原样透传给调用方"
    # 流读完后传输层自己收尾（_StreamTee._done），不必等 gateway
    assert rec.finished, "流读完后应当收尾"
    # 存的是**原始 SSE 帧**（不是解析后的文本）：排查"上游到底发了什么"要看原文，
    # 正文是落库时由 extract_from_response 另外解析出来的
    assert rec.finished[0]["response_text"] == sse.decode()
    assert rec.finished[0]["status"] == "success"


@pytest.mark.anyio
async def test_stream_marks_first_token_once():
    """首 token 耗时只记第一次：每次分块都覆盖会让这个指标变成"最后一个分块的时间"。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(
            lambda r: _sse([b"data: 1\n\n", b"data: 2\n\n"])), rec)
        async with client:
            async with client.stream("POST", "https://api.test/x", json={}) as resp:
                async for _ in resp.aiter_bytes():
                    pass
    finally:
        llm_log.unbind(token)

    assert rec.first_token_ms is not None


@pytest.mark.anyio
async def test_stream_close_without_reading_still_records():
    """客户端提前断开（一个字节都不读就 close）：也要收尾，否则这条调用永远"没有日志"。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(lambda r: _sse([b"data: 1\n\n"])), rec)
        async with client:
            async with client.stream("POST", "https://api.test/x", json={}):
                pass
    finally:
        llm_log.unbind(token)

    assert rec.finished, "关闭时也必须收尾"


@pytest.mark.anyio
async def test_stream_done_is_idempotent():
    """读完与 close 都会走 _done：只能落一次，重复落会产生两条记录。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(lambda r: _sse([b"data: 1\n\n"])), rec)
        async with client:
            async with client.stream("POST", "https://api.test/x", json={}) as resp:
                async for _ in resp.aiter_bytes():
                    pass
    finally:
        llm_log.unbind(token)

    assert len(rec.finished) == 1


@pytest.mark.anyio
async def test_stream_error_status_marks_error():
    """流式请求本身返回 4xx/5xx：收尾时状态要是 error，不能因为"是流"就默认成功。"""
    rec = _Recorder()
    token = llm_log.bind(rec)
    try:
        client = llm_log.wrap_client(_client(
            lambda r: httpx.Response(500, stream=_SseStream([b'data: {"error":"boom"}\n\n']),
                                     headers={"content-type": "text/event-stream"})), rec)
        async with client:
            async with client.stream("POST", "https://api.test/x", json={}) as resp:
                async for _ in resp.aiter_bytes():
                    pass
    finally:
        llm_log.unbind(token)

    assert rec.finished[0]["status"] == "error"
    assert "HTTP 500" in rec.finished[0]["error"]


# --------------------------------------------------------------------------- 包装幂等

def test_wrap_client_is_idempotent():
    """重复包装会叠出两层传输层（同一请求记两遍）。已经包过就直接返回。"""
    client = _client(lambda r: httpx.Response(200))
    first = llm_log.wrap_client(client, _Recorder())
    second = llm_log.wrap_client(client, _Recorder())
    assert first is client and second is client
    assert isinstance(client._transport, llm_log._RecordingTransport)
    assert not isinstance(client._transport._inner, llm_log._RecordingTransport)
