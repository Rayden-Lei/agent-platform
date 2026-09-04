"""ASGI 中间件：请求 ID 与访问日志。

刻意不用 Starlette 的 BaseHTTPMiddleware：它会把响应重新包一层，
对 SSE 流式响应与客户端中断的语义有影响（对话接口依赖生成器的 finally 做运行记录收尾）。
纯 ASGI 实现只在 http.response.start 时追加一个响应头，不碰响应体，也不改变异常传播路径。
"""
import logging
import time

from starlette.datastructures import Headers

from app.core.request_context import (
    REQUEST_ID_HEADER,
    new_request_id,
    reset_request_id,
    sanitize_request_id,
    set_request_id,
)

logger = logging.getLogger("app.access")

# 探活接口被监控系统高频调用，每次打 INFO 会淹没业务日志，降到 DEBUG
_QUIET_PATHS = {"/health"}


class RequestContextMiddleware:
    """为每个 HTTP 请求分配追踪 ID，回写响应头，并记录一条访问日志。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = sanitize_request_id(incoming) or new_request_id()
        token = set_request_id(request_id)
        # 同时写进 ASGI scope：未处理异常的 handler 由更外层的 ServerErrorMiddleware 调用，
        # 那时本中间件的 finally 已经把 contextvar 重置了，只能从 scope 里取回同一个 ID。
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        method = scope.get("method", "-")
        path = scope.get("path", "-")
        status_code = 500  # 下游抛异常时不会走 http.response.start，按 500 记

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message["headers"] = list(message.get("headers") or []) + [
                    (REQUEST_ID_HEADER.encode(), request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            # 堆栈由上层的未处理异常 handler 记录，这里只补一条定位信息，避免同一异常打三份堆栈
            logger.warning("请求处理异常 %s %s: %s: %s", method, path, type(e).__name__, e)
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
            logger.log(level, "%s %s %s %.0fms", method, path, status_code, elapsed_ms)
            reset_request_id(token)
