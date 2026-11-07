"""模型调用全量日志（2026-11-08）：记录每一次请求的完整报文。

**做什么**：在模型调用的 HTTP 客户端上挂一层，把
- 实际请求地址（完整 URL，能看出打到了哪个上游）
- 请求体（messages 全文、工具定义、温度等参数）
- 响应体（含流式 SSE 原文）
- 解析出的正文与思考过程、工具调用、用量、耗时、错误原文
落进 `llm_calls` 表。

**为什么放 HTTP 层而不是 LLM 层**：LangChain 的消息对象已经丢了原始报文 ——
看不出实际发给上游的字段名、看不出对方返回的 SSE 帧长什么样、看不出重试了几次。
排查"模型为什么这么答""为什么没调工具"时，能回答问题的只有原始报文。

**打码口径**：只打凭据。api_key 换成 ***，其余（地址、请求体、响应体、错误原文）
全部原样保留。凭据不进日志是硬约束；除此之外对使用者完全透明。

**体积**：单条报文截断到 LLM_LOG_MAX_CHARS（默认 256KB），超出时在末尾注明原文长度。
截断是"看得见的不完整"，不是悄悄丢。

**失败不影响主流程**：日志写入的任何异常只记 WARNING —— 记日志把对话搞挂是不可接受的。
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 请求头里这些键的值要打码（凭据不进日志）
_SECRET_HEADERS = ("authorization", "api-key", "x-api-key", "cookie", "token", "secret")
# 请求/响应体里这些键的值要打码（有些厂商把 key 放在 body 里，如 Gemini 的 ?key=）
_SECRET_BODY_KEYS = ("api_key", "apikey", "authorization", "access_token", "token", "secret", "password")
# 这些路径片段是上游地址里带凭据的常见位置（如 ?key=xxx）
_URL_SECRET_RE = re.compile(r"([?&](?:key|api_key|api-key|token|access_token)=)([^&]+)", re.IGNORECASE)


def mask_url(url: str) -> str:
    """把地址里的 key 打码，其余原样保留（地址本身要能看见，才能排查打到了哪个上游）。"""
    return _URL_SECRET_RE.sub(lambda m: m.group(1) + "***", url or "")


def mask_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in dict(headers or {}).items():
        out[str(k)] = "***" if str(k).lower() in _SECRET_HEADERS else str(v)
    return out


def mask_body(value: Any) -> Any:
    """递归打码请求 / 响应体里的凭据键。其余字段（messages、tools、temperature…）原样保留。

    工具定义里的参数值不动：那是模型要传的东西，不是凭据。
    """
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in _SECRET_BODY_KEYS and isinstance(v, str) else mask_body(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_body(v) for v in value]
    return value


def clamp_text(text: str | None, limit: int | None = None) -> tuple[str | None, bool]:
    """按字符数截断，返回 (文本, 是否截断)。截断时在末尾注明原文长度。"""
    if text is None:
        return None, False
    cap = limit if limit is not None else settings.LLM_LOG_MAX_CHARS
    if len(text) <= cap:
        return text, False
    return text[:cap] + f"\n…（已截断，原文 {len(text)} 字符）", True


def clamp_obj(obj: Any, limit: int | None = None) -> tuple[Any, bool]:
    """对象按序列化后的字符数判断是否超限；超限时退化成带说明的字符串。"""
    if obj is None:
        return None, False
    try:
        serialized = json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"_error": "内容无法序列化", "_repr": str(obj)[:2000]}, False
    cap = limit if limit is not None else settings.LLM_LOG_MAX_CHARS
    if len(serialized) <= cap:
        return obj, False
    return {"_truncated": True, "_original_chars": len(serialized), "_preview": serialized[:cap]}, True


def summarize_tools(body: Any) -> list[dict]:
    """从请求体里取出工具定义（只留名字 / 描述 / 参数声明），用于"给了模型什么工具"。"""
    if not isinstance(body, dict):
        return []
    tools = body.get("tools")
    if not isinstance(tools, list):
        return []
    out: list[dict] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else item
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        params = fn.get("parameters") or fn.get("input_schema") or {}
        out.append({
            "name": str(name),
            "description": str(fn.get("description") or "")[:2000],
            # 参数声明原样保留：排查"模型为什么没传某个参数"要看声明长什么样
            "parameters": params if isinstance(params, (dict, list)) else {},
        })
    return out


def extract_from_response(text: str | None) -> dict:
    """从响应原文里抽出正文、思考过程、工具调用、用量。流式（SSE）与非流式都认。

    流式响应是一串 `data: {...}` 帧：把 delta 的 content / reasoning_content 拼起来，
    tool_calls 按 index 累积参数。解析失败不算错 —— 对方可能就是返回了别的东西，
    那时原文照样保存着，人能自己看。
    """
    if not text:
        return {"content": "", "reasoning": "", "tool_calls": [], "usage": {}}
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: dict[int, dict] = {}
    usage: dict = {}

    def absorb(obj: dict) -> None:
        nonlocal usage
        if isinstance(obj.get("usage"), dict) and obj["usage"]:
            usage = obj["usage"]
        choices = obj.get("choices")
        if not isinstance(choices, list):
            return
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else choice.get("message")
            if not isinstance(delta, dict):
                continue
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                content_parts.append(piece)
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                reasoning_parts.append(reasoning)
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                idx = tc.get("index", 0)
                entry = tool_calls.setdefault(idx, {"name": "", "arguments": ""})
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                if fn.get("name"):
                    entry["name"] = fn["name"]
                if fn.get("arguments"):
                    entry["arguments"] += fn["arguments"] if isinstance(fn["arguments"], str) else json.dumps(fn["arguments"], ensure_ascii=False)

    stripped = text.lstrip()
    if stripped.startswith("data:") or "\ndata:" in text:
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                absorb(json.loads(payload))
            except json.JSONDecodeError:
                continue
    else:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                absorb(parsed)
        except json.JSONDecodeError:
            pass

    parsed_calls = []
    for entry in tool_calls.values():
        if not entry["name"] and not entry["arguments"]:
            continue
        args: Any = entry["arguments"]
        try:
            args = json.loads(entry["arguments"]) if entry["arguments"] else {}
        except json.JSONDecodeError:
            pass  # 参数不是合法 JSON 就原样留着，人能看出来模型拼错了
        parsed_calls.append({"name": entry["name"], "arguments": args})
    return {"content": "".join(content_parts), "reasoning": "".join(reasoning_parts),
            "tool_calls": parsed_calls, "usage": usage}


class LlmCallRecorder:
    """一次模型调用的采集上下文。由 ChatHooks 创建，绑定当前线程 / 上下文。"""

    def __init__(self, *, purpose: str = "chat", run_id: int | None = None,
                 model_id: int | None = None, model_name: str = ""):
        self.purpose = purpose
        self.run_id = run_id
        self.model_id = model_id
        self.model_name = model_name
        self.url = ""
        self.method = "POST"
        self.request_body: dict | None = None
        self.response_body: str | None = None
        self.status = "success"
        self.http_status: int | None = None
        self.error: str | None = None
        self.truncated = False
        self.started = time.perf_counter()
        self.first_token_ms: int | None = None
        self._recorded = False

    def mark_first_token(self) -> None:
        if self.first_token_ms is None:
            self.first_token_ms = int((time.perf_counter() - self.started) * 1000)

    def finish(self, *, response_text: str | None = None, status: str | None = None,
               http_status: int | None = None, error: str | None = None) -> None:
        """收尾并落库。重复调用是幂等的（只写一次）。"""
        if self._recorded:
            return
        self._recorded = True
        if response_text is not None:
            self.response_body = response_text
        if status:
            self.status = status
        if http_status is not None:
            self.http_status = http_status
        if error:
            self.error = error
        try:
            _persist(self)
        except Exception:
            # 记日志失败绝不能影响对话本身
            logger.warning("模型调用日志写入失败 run_id=%s url=%s", self.run_id, self.url, exc_info=True)


# 用 contextvars 而不是 threading.local：对话是异步的，同一个线程里会同时跑多个请求
# （TestClient / uvicorn 都是这样）。threading.local 在协程之间是共享的，
# 两个并发对话会互相覆盖对方的采集器 —— 结果是一边记到另一边头上，甚至记成别人的 run_id。
# contextvars 随 asyncio task 复制，天然隔离。
_CURRENT: contextvars.ContextVar[LlmCallRecorder | None] = contextvars.ContextVar("llm_call_recorder", default=None)


def current() -> LlmCallRecorder | None:
    """取当前上下文的采集器（没有就是 None，调用方照常发请求）。"""
    return _CURRENT.get()


def bind(recorder: LlmCallRecorder | None) -> contextvars.Token:
    """绑定采集器，返回 token；收尾时用 unbind(token) 精确还原（而不是置空，
    否则嵌套调用（一轮对话里再发摘要）会把自己的父采集器一起清掉）。"""
    return _CURRENT.set(recorder)


def unbind(token: contextvars.Token) -> None:
    """还原到 bind 之前的采集器。token 必须来自同一个上下文，跨 task 传会 ValueError。"""
    try:
        _CURRENT.reset(token)
    except ValueError:
        # 跨 task 传 token（极端情况下的取消）：退化成置空，不要让日志问题打断对话
        _CURRENT.set(None)


def _persist(rec: LlmCallRecorder) -> None:
    """落库。用独立 session：日志不该参与调用方的业务事务（更不该把它一起回滚）。"""
    from app.db.models import LlmCall
    from app.db.session import SessionLocal

    extracted = extract_from_response(rec.response_body)
    body, truncated_body = clamp_obj(mask_body(rec.request_body))
    resp, truncated_resp = clamp_text(rec.response_body)
    text, truncated_text = clamp_text(extracted["content"] or None)
    reasoning, _ = clamp_text((extracted["reasoning"] or "")[:50_000] or None)
    # 一次调用的用量可能分散在多个分块里，取最后一个非空的（已由 extract 合并）
    usage = extracted["usage"] or {}
    db = SessionLocal()
    try:
        db.add(LlmCall(
            run_id=rec.run_id, model_id=rec.model_id, model_name=rec.model_name[:128],
            purpose=rec.purpose[:24], url=mask_url(rec.url)[:512], method=rec.method[:8],
            request_body=body, response_body=resp, response_text=text, reasoning_text=reasoning,
            tools_offered=summarize_tools(rec.request_body), tool_calls=extracted["tool_calls"],
            status=rec.status[:16], http_status=rec.http_status, error=rec.error,
            prompt_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
            first_token_ms=rec.first_token_ms,
            duration_ms=int((time.perf_counter() - rec.started) * 1000),
            truncated=truncated_body or truncated_resp or truncated_text,
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class _StreamTee(httpx.AsyncByteStream):
    """包住响应的字节流：边读边攒，读完（或关闭）时把全文交给采集器。

    为什么必须在这里攒：流式响应一旦被 `aread()` 就被吃掉了，调用方拿不到分块；
    而只有"读到的原始字节"才是排查依据（SSE 帧长什么样、有没有被上游截断）。
    """

    def __init__(self, inner: httpx.AsyncByteStream, rec: LlmCallRecorder):
        self._inner = inner
        self._rec = rec
        self._chunks: list[bytes] = []

    async def __aiter__(self):
        async for chunk in self._inner:
            self._chunks.append(chunk)
            self._rec.mark_first_token()
            yield chunk
        self._done()

    async def aclose(self) -> None:
        self._done()
        await self._inner.aclose()

    def _done(self) -> None:
        if self._rec._recorded:
            return
        raw = b"".join(self._chunks)
        try:
            body = raw.decode("utf-8", errors="replace")
        except Exception:
            body = ""
        status = self._rec.http_status or 0
        self._rec.finish(response_text=body,
                         status="success" if 0 < status < 400 else "error",
                         error=None if 0 < status < 400 else f"HTTP {status}")


class _RecordingTransport(httpx.AsyncBaseTransport):
    """异步传输包装：在真正发请求前后抓报文。"""

    def __init__(self, inner: httpx.AsyncBaseTransport):
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        rec = current()
        if rec is None:
            return await self._inner.handle_async_request(request)
        rec.url = mask_url(str(request.url))
        rec.method = request.method
        # 请求体：尽力按 JSON 解，解不开就存原文（能看见总比看不见好）
        try:
            raw = request.content.decode("utf-8", errors="replace") if request.content else ""
        except Exception:
            raw = ""
        if raw:
            try:
                rec.request_body = json.loads(raw)
            except json.JSONDecodeError:
                rec.request_body = {"_raw": raw}
        try:
            response = await self._inner.handle_async_request(request)
        except Exception as e:
            rec.finish(status="error", error=f"{type(e).__name__}: {e}")
            raise
        rec.http_status = response.status_code
        # 响应体不在 transport 里读（会把流吃掉），交给 _StreamTee 边读边攒
        response.stream = _StreamTee(response.stream, rec)  # type: ignore[assignment]
        return response


def wrap_client(client: httpx.AsyncClient, recorder: LlmCallRecorder) -> httpx.AsyncClient:
    """给 AsyncClient 换上采集传输层。返回同一个 client（原地改 transport，不新建连接池）。

    用原地替换而不是新建：ChatOpenAI 在构造时就抓住了这个 client，
    换一个新对象它不会跟着换。
    """
    if isinstance(client._transport, _RecordingTransport):
        return client
    client._transport = _RecordingTransport(client._transport)  # noqa: SLF001 采集需要
    bind(recorder)
    return client
