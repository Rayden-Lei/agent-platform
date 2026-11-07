"""本地起一个真实的 MCP server，用官方 SDK 的 MCPServer + Streamable HTTP。

用途：让 MCP 的**协议层**（握手、list_tools、tools/call、SSE 分帧）被测到。
之前 test_mcp.py 把客户端整体打桩，协议一旦有偏差（SDK 升级、头没带上、传输选错）
测试全绿而线上全挂 —— 这个夹具就是补这个洞。

做法：uvicorn 在本机随机端口起 MCPServer 的 streamable_http_app，测试用真实 HTTP 连它。
不起子进程（避免 pytest 里 fork 出难以回收的进程），用线程跑 uvicorn.Server，
夹具退出时 should_exit + join，端口立即释放。
"""
from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import uvicorn
from mcp.server.mcpserver import MCPServer


def _free_port() -> int:
    """拿一个空闲端口：先 bind 再关，交给 uvicorn 用（中间极短的空窗，本机测试可接受）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@dataclass
class LocalMcp:
    """一个跑着的本地 MCP server。"""

    url: str
    port: int
    server: MCPServer
    _uv: uvicorn.Server
    _thread: threading.Thread
    # 测试可以往里塞断言：每次 tools/call 时记录 (name, args)
    calls: list = field(default_factory=list)

    def stop(self) -> None:
        self._uv.should_exit = True
        self._thread.join(timeout=10)


def build_server(*, recorder: list | None = None, fail: Callable[[], None] | None = None) -> MCPServer:
    """造一个带固定工具的 MCPServer。

    工具刻意覆盖三种参数形态：
    - echo(text: str)           纯字符串
    - add(a: int, b: int)       数字 → 验证 required 与类型转换
    - tags(tags: list[str])     数组 → 验证客户端的降级 + 还原是否真的能打通
    fail 给定时，慢失败工具会抛异常，用来验证 is_error → {"error": ...} 的映射。
    """
    server = MCPServer("pytest-mcp")

    @server.tool()
    def echo(text: str) -> str:
        """原样回声，用于验证最基本的 tools/call。"""
        if recorder is not None:
            recorder.append(("echo", {"text": text}))
        return "echo:" + text

    @server.tool()
    def add(a: int, b: int) -> str:
        """两个整数相加。"""
        if recorder is not None:
            recorder.append(("add", {"a": a, "b": b}))
        return str(a + b)

    @server.tool()
    def tags(tags: list[str]) -> str:
        """把数组拼成字符串，用于验证深度参数能真的送到远端（而不是被降级成字符串）。"""
        if recorder is not None:
            recorder.append(("tags", {"tags": tags}))
        return ",".join(tags)

    @server.tool()
    def boom() -> str:
        """总是失败，用于验证远端报错映射成 {"error": ...}。"""
        raise RuntimeError("远端炸了")

    return server


def start(*, recorder: list | None = None, host_header: str | None = None) -> LocalMcp:
    """起一个本地 MCP server 并等到它真能接收请求。"""
    server = build_server(recorder=recorder)
    port = _free_port()
    app = server.streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True, name=f"mcp-{port}")
    thread.start()
    # 等它真的开始监听：uv.started 由 uvicorn 在 startup 结束后置真
    deadline = time.time() + 20
    while time.time() < deadline:
        if uv.started:
            break
        time.sleep(0.02)
    else:  # pragma: no cover 起不来就是环境问题，直接失败并说明
        raise RuntimeError(f"本地 MCP server 在 {port} 端口 20 秒内没起来")
    # 端口通了不代表 ASGI 就绪，再探一次 TCP 连接
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.02)
    return LocalMcp(url=f"http://127.0.0.1:{port}/mcp", port=port, server=server, _uv=uv, _thread=thread)
