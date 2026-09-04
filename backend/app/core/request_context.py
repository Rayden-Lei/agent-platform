"""请求上下文：贯穿一次请求的追踪 ID。

日志、错误响应体、响应头共用同一个 ID，排查线上问题时用它把一次调用的所有日志串起来：
用户报错时只需要给出响应里的 trace_id，就能 grep 出这次请求的全部日志。

用 contextvar 而不是层层传参：中间件设置一次，任意深度的日志调用都能取到，
并发请求之间天然隔离（每个 asyncio 任务持有独立副本）。
"""
import logging
import re
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "x-request-id"

# 没有请求上下文时（启动阶段、调度线程、后台任务）取到这个值，日志格式不会因此报错
NO_REQUEST_ID = "-"

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)

# 只接受安全字符：请求 ID 会进日志与响应头，外部传入的值不做限制会造成日志注入与响应头注入
_SAFE_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def sanitize_request_id(value: str | None) -> str | None:
    """校验调用方传入的追踪 ID；不合法返回 None，由调用方另行生成。"""
    if not value:
        return None
    value = value.strip()
    return value if _SAFE_ID.match(value) else None


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str):
    """返回 token，供 reset_request_id 还原，避免污染同线程的后续任务。"""
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)


class RequestIdFilter(logging.Filter):
    """给每条日志补 request_id 字段，供 formatter 使用。

    挂在 root handler 上，第三方库（uvicorn、sqlalchemy）的日志也能带上同一个 ID。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
