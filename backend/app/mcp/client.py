"""MCP 客户端（docs/17 §5，P5）：只用 HTTP / SSE 传输，不接 stdio。

用官方 SDK `mcp`（锁 2.3.0）：协议细节（握手、版本协商、SSE 帧、分页）都由它处理，
自己抄一遍只会抄出偏差。

**不做长连接池**（§5.3 第 2 条）：SSE 会话要 initialize 握手，池化就得引入超时与重连状态机，
首版不值得。代价是每次调用多一次握手 RTT。因此本模块的每个入口都是"开一次会话、做完、关掉"。

两种传输：
- `http`  Streamable HTTP：所有报文 POST 到同一个 url，响应可能是 JSON 也可能是 SSE 流
- `sse`   旧版 HTTP+SSE：先 GET 拿一条流，服务端告知 POST 端点

stdio 一律不做：那等于在服务器上执行配置里写的任意命令（同类问题见 MaxKB CVE-2026-39417），
还要在镜像里装运行时。
"""
from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

logger = logging.getLogger(__name__)

# 一次同步最多接多少个远端工具：工具太多会让模型的工具列表爆掉
MAX_REMOTE_TOOLS = 100
# 远端工具返回的文本上限：一条工具结果会进模型上下文，不设上限时一次调用就能吃光窗口
MAX_RESULT_CHARS = 100_000


class McpError(Exception):
    """MCP 调用失败（连不上、协议错、远端报错）。调用方一律转成工具结果里的 error，不往上抛。"""


@dataclass
class McpTool:
    """远端工具的描述，对应 `tools/list` 返回的一项。"""

    name: str
    description: str
    input_schema: dict


def _auth_headers(headers: dict, secret: str | None) -> dict[str, str]:
    """拼请求头：配置里的非敏感头 + 凭据。凭据走 Authorization: Bearer（MCP 的通行做法）。"""
    out = {str(k): str(v) for k, v in (headers or {}).items()}
    if secret:
        out["Authorization"] = f"Bearer {secret}"
    return out


class _Session:
    """一次会话：负责建连、握手、关闭。用 AsyncExitStack 保证任意一步失败都能把连接收干净。"""

    def __init__(self, url: str, transport: str, headers: dict[str, str], timeout: float):
        self.url = url
        self.transport = transport
        self.headers = headers
        self.timeout = timeout
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> ClientSession:
        try:
            if self.transport == "sse":
                read, write = await self._stack.enter_async_context(
                    sse_client(self.url, headers=self.headers, timeout=self.timeout, sse_read_timeout=self.timeout)
                )
            else:
                # streamable_http_client 没有 headers 参数，头只能随 client 传。
                # 用 SDK 自己的工厂建 client：它内部用的是 httpx2（2.x 起换掉了 httpx），
                # 自己 new 一个 httpx.AsyncClient 会因为类型不匹配被 SDK 拒收。
                http_client = create_mcp_http_client(
                    headers=self.headers,
                    timeout=httpx2.Timeout(self.timeout, read=self.timeout),
                )
                self._stack.push_async_callback(http_client.aclose)
                read, write = await self._stack.enter_async_context(
                    streamable_http_client(self.url, http_client=http_client)
                )
            self._session = await self._stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=self.timeout)
            )
            await self._session.initialize()
            return self._session
        except Exception:
            await self._stack.aclose()
            raise

    async def __aexit__(self, *exc) -> None:
        try:
            await self._stack.aclose()
        except Exception:
            # 清理失败不该盖掉调用本身的结果：只记日志
            logger.warning("关闭 MCP 会话失败 url=%s", self.url, exc_info=True)


def _open(url: str, transport: str, headers: dict, secret: str | None, timeout: float) -> _Session:
    return _Session(url, transport, _auth_headers(headers, secret), timeout)


def _wrap_error(e: Exception) -> McpError:
    """把 SDK 与 httpx 的异常转成一句人话。SDK 的异常有时是 ExceptionGroup，取里面的根因。"""
    if isinstance(e, McpError):
        return e
    if isinstance(e, BaseExceptionGroup):
        inner = next((x for x in e.exceptions if not isinstance(x, BaseExceptionGroup)), e.exceptions[0] if e.exceptions else e)
        return _wrap_error(inner if isinstance(inner, Exception) else e)
    if isinstance(e, (httpx2.HTTPError, httpx2.StreamError)):
        return McpError(f"连接 MCP 服务器失败：{type(e).__name__}")
    return McpError(f"MCP 调用失败：{type(e).__name__}: {e}")


async def probe(url: str, transport: str, headers: dict, secret: str | None, timeout: float) -> list[McpTool]:
    """连一次并取工具清单。同步工具与"测试连接"共用这一条路径。"""
    try:
        async with _open(url, transport, headers, secret, timeout) as session:
            result = await session.list_tools()
    except McpError:
        raise
    except Exception as e:
        raise _wrap_error(e) from e

    tools: list[McpTool] = []
    for item in (result.tools or [])[:MAX_REMOTE_TOOLS]:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        schema = getattr(item, "input_schema", None)
        tools.append(McpTool(
            name=name,
            description=str(getattr(item, "description", "") or "").strip(),
            input_schema=schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
        ))
    return tools


def _content_to_text(content: Any) -> str:
    """把 tools/call 的 content 压成文本。

    文本片段直接拼；图片、资源这类二进制内容不塞进模型上下文（会把一轮对话撑爆），
    只留一句占位说明，让模型知道"拿到了但没展开"。
    """
    parts: list[str] = []
    for item in content or []:
        kind = getattr(item, "type", None)
        if kind == "text":
            parts.append(str(getattr(item, "text", "") or ""))
        elif kind == "image":
            parts.append(f"[图片 {getattr(item, 'mime_type', '') or ''}，未展开]".strip())
        elif kind == "resource":
            res = getattr(item, "resource", None)
            text = getattr(res, "text", None)
            parts.append(str(text) if text is not None else f"[资源 {getattr(res, 'uri', '') or ''}，未展开]".strip())
        else:
            parts.append(f"[{kind} 内容，未展开]")
    text = "\n".join(p for p in parts if p)
    if len(text) > MAX_RESULT_CHARS:
        return text[:MAX_RESULT_CHARS] + f"…（已截断，原文 {len(text)} 字）"
    return text


async def call(url: str, transport: str, headers: dict, secret: str | None, timeout: float,
               name: str, arguments: dict) -> dict:
    """调一个远端工具。返回统一契约 {"result": ...} 或 {"error": ...}，与 HTTP 工具一致。"""
    try:
        async with _open(url, transport, headers, secret, timeout) as session:
            result = await session.call_tool(name, arguments or {})
    except McpError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(_wrap_error(e))}

    text = _content_to_text(getattr(result, "content", None))
    if getattr(result, "is_error", False):
        return {"error": text or "MCP 工具执行失败"}
    return {"result": text}
