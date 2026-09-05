"""全局 IP 黑名单中间件（FR-026）：命中 IP_DENYLIST 的来源一律 403，/health 除外（探活不该被封）。

- 独立于请求 ID 中间件，并注册在 CORS 中间件内层：403 会经过 CORS 处理带上跨域头，
  浏览器端能读到可读的 403 而不是"网络错误"；请求 ID 中间件在更外层，trace_id 与响应头照常带上。
- 纯 ASGI 实现，理由同 middleware.py：不重新包装响应体，不影响 SSE。
- 客户端 IP 由外层的请求 ID 中间件解析并放进 contextvar，这里只做匹配。
"""
import ipaddress
import json
import logging
from functools import lru_cache

from app.config import settings
from app.core.request_context import get_client_ip, get_request_id

logger = logging.getLogger(__name__)

_EXEMPT_PATHS = {"/health"}


@lru_cache(maxsize=4)
def _parse_networks(raw: str) -> tuple:
    """逗号分隔的 IP/CIDR → 网络对象元组。按原始字符串缓存：配置不变就不重复解析，合法性已在 Settings 校验。"""
    return tuple(
        ipaddress.ip_network(item.strip(), strict=False)
        for item in raw.split(",")
        if item.strip()
    )


def is_denied(ip: str | None, raw_denylist: str) -> bool:
    """来源 IP 是否命中黑名单。IP 缺失或不是合法字面量（如测试客户端的 "testclient"）按未命中处理。"""
    networks = _parse_networks(raw_denylist)
    if not networks or not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


async def _send_json(send, status: int, body: dict) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(payload)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": payload})


class IpFilterMiddleware:
    """按 settings.IP_DENYLIST 拒绝来源 IP；每次请求读当前配置，便于测试与热改。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        ip = get_client_ip()
        if is_denied(ip, settings.IP_DENYLIST):
            # 被拒绝是预期内的安全事件，不是故障：记 WARN 留痕即可，不打堆栈
            logger.warning("来源 IP 命中黑名单，已拒绝 ip=%s %s %s", ip, scope.get("method", "-"), scope.get("path", "-"))
            await _send_json(send, 403, {"detail": "来源 IP 被拒绝", "trace_id": get_request_id()})
            return
        await self.app(scope, receive, send)
