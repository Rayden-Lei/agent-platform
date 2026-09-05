"""请求上下文：贯穿一次请求的追踪 ID 与客户端 IP。

日志、错误响应体、响应头共用同一个 ID，排查线上问题时用它把一次调用的所有日志串起来：
用户报错时只需要给出响应里的 trace_id，就能 grep 出这次请求的全部日志。
客户端 IP 由审计、IP 黑白名单、按 IP 限流共用，同样只在中间件解析一次。

用 contextvar 而不是层层传参：中间件设置一次，任意深度的日志调用都能取到，
并发请求之间天然隔离（每个 asyncio 任务持有独立副本）。
"""
import ipaddress
import logging
import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers

from app.config import settings

REQUEST_ID_HEADER = "x-request-id"
# 反向代理传递客户端地址的两个常见头；只在 TRUSTED_PROXY_ENABLED 打开时才读
CLIENT_IP_HEADER_REAL = "x-real-ip"
CLIENT_IP_HEADER_FORWARDED = "x-forwarded-for"

# 没有请求上下文时（启动阶段、调度线程、后台任务）取到这个值，日志格式不会因此报错
NO_REQUEST_ID = "-"

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)
# 客户端 IP 无请求上下文时为 None：审计表里存空，而不是存一个假地址
_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)

# 只接受安全字符：请求 ID 会进日志与响应头，外部传入的值不做限制会造成日志注入与响应头注入
_SAFE_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


def new_request_id() -> str:
    """生成 16 位十六进制追踪 ID（本机生成，无外部输入，天然安全）。"""
    return uuid.uuid4().hex[:16]


def sanitize_request_id(value: str | None) -> str | None:
    """校验调用方传入的追踪 ID；不合法返回 None，由调用方另行生成。"""
    if not value:
        return None
    value = value.strip()
    return value if _SAFE_ID.match(value) else None


def get_request_id() -> str:
    """当前上下文的 request_id；无请求上下文时（启动阶段/调度线程/后台任务）为 NO_REQUEST_ID("-")。"""
    return _request_id.get()


def set_request_id(value: str):
    """返回 token，供 reset_request_id 还原，避免污染同线程的后续任务。"""
    return _request_id.set(value)


def reset_request_id(token) -> None:
    """用 set_request_id 返回的 token 还原 contextvar，防止污染同线程的后续任务。"""
    _request_id.reset(token)


def _valid_ip(value: str | None) -> str | None:
    """转发头里的地址只接受合法 IP 字面量：它会进日志与审计表，不能带任意文本。"""
    if not value:
        return None
    value = value.strip()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def resolve_client_ip(scope) -> str | None:
    """从 ASGI scope 解析客户端 IP。

    TRUSTED_PROXY_ENABLED 打开时才看转发头：先 X-Real-IP（nginx 单跳最不易配错），
    再 X-Forwarded-For 的首项；头缺失或不是合法 IP 时回退到连接对端。
    默认关闭：能直连后端的调用方可以随意伪造这两个头，信任它们等于让黑白名单形同虚设。
    """
    if settings.TRUSTED_PROXY_ENABLED:
        headers = Headers(scope=scope)
        real_ip = _valid_ip(headers.get(CLIENT_IP_HEADER_REAL))
        if real_ip:
            return real_ip
        forwarded = headers.get(CLIENT_IP_HEADER_FORWARDED) or ""
        first = _valid_ip(forwarded.split(",")[0]) if forwarded else None
        if first:
            return first
    client = scope.get("client")
    return client[0] if client else None


def get_client_ip() -> str | None:
    """当前请求的客户端 IP；无请求上下文（调度线程、脚本）时为 None。"""
    return _client_ip.get()


def set_client_ip(value: str | None):
    """返回 token，供 reset_client_ip 还原。"""
    return _client_ip.set(value)


def reset_client_ip(token) -> None:
    _client_ip.reset(token)


class RequestIdFilter(logging.Filter):
    """给每条日志补 request_id 字段，供 formatter 使用。

    挂在 root handler 上，第三方库（uvicorn、sqlalchemy）的日志也能带上同一个 ID。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
