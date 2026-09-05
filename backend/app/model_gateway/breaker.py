"""模型调用熔断（FR-027）：按模型连续失败计数，熔断期内快速失败，半开探测自动恢复。

- 状态存进程内存：单实例部署形态下够用；多实例各自熔断（`08-运行与部署.md` 已注明，与调度器多实例问题同类）。
- 只计连续失败：连接失败、超时、上游 429 与 5xx。4xx 配置 / 参数错误不计——它们不会因为等待而恢复，
  熔断反而会掩盖真正原因。
- 打开时 WARN、恢复时 INFO，状态经 `status()` 接进 `/system/status`（`06-后端规范.md` 13.3 的三件事）。
"""
import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import openai

from app.config import settings
from app.core.exceptions import BizError

logger = logging.getLogger(__name__)

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"

# 可注入的时钟：测试用固定时间推进"打开期"是否到期
_clock = time.time


@dataclass
class ModelBreaker:
    model_id: int
    name: str
    state: str = STATE_CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None
    probe_in_flight: bool = False  # 半开态是否已有探测请求在跑；只放一个


_registry: dict[int, ModelBreaker] = {}
# 半开态"只放一个探测"的判定必须原子：对话路由是 async 与线程混跑，两个请求可能同时到达
_lock = threading.Lock()


def _breaker(model_id: int, name: str) -> ModelBreaker:
    b = _registry.get(model_id)
    if b is None:
        b = ModelBreaker(model_id=model_id, name=name)
        _registry[model_id] = b
    b.name = name  # 模型改名后状态里显示新名字
    return b


def counts_as_failure(exc: BaseException) -> bool:
    """哪些异常计入连续失败：连接 / 超时类、上游 429 与 5xx；其余（401 / 400 / 404 等）不计。"""
    if isinstance(exc, (openai.APIConnectionError, httpx.TransportError, TimeoutError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _retry_after(b: ModelBreaker, now: float) -> int:
    remaining = settings.MODEL_BREAKER_OPEN_SECONDS - (now - (b.opened_at or now))
    return max(math.ceil(remaining), 1)


def _unavailable(b: ModelBreaker, retry_after: int) -> BizError:
    return BizError(
        503,
        f"模型「{b.name}」暂时不可用（熔断中，{retry_after} 秒后自动重试）",
        headers={"Retry-After": str(retry_after)},
    )


def before_call(model_id: int, name: str) -> None:
    """调用前判定：closed 放行；open 未到期直接 503；到期转 half_open 且只放一个探测，其余仍 503。"""
    if settings.MODEL_BREAKER_FAIL_THRESHOLD <= 0:
        return
    with _lock:
        b = _breaker(model_id, name)
        if b.state == STATE_CLOSED:
            return
        now = _clock()
        if b.state == STATE_OPEN:
            if now - (b.opened_at or now) < settings.MODEL_BREAKER_OPEN_SECONDS:
                raise _unavailable(b, _retry_after(b, now))
            b.state = STATE_HALF_OPEN
            b.probe_in_flight = False
            logger.info("模型熔断进入半开 model_id=%s name=%s，放行一个探测请求", model_id, name)
        if b.probe_in_flight:
            raise _unavailable(b, 1)
        b.probe_in_flight = True


def record_success(model_id: int, name: str) -> None:
    """一次成功即清零连续失败；半开探测成功则关闭熔断。"""
    with _lock:
        b = _breaker(model_id, name)
        if b.state != STATE_CLOSED:
            logger.info("模型熔断关闭 model_id=%s name=%s", model_id, name)
        b.state = STATE_CLOSED
        b.consecutive_failures = 0
        b.opened_at = None
        b.probe_in_flight = False


def record_failure(model_id: int, name: str, exc: BaseException) -> bool:
    """记录一次失败，返回是否计入连续失败。

    半开探测遇到不计数的错误（如 401）：上游可达只是配置有问题，按恢复处理，关闭熔断。
    """
    threshold = settings.MODEL_BREAKER_FAIL_THRESHOLD
    with _lock:
        b = _breaker(model_id, name)
        b.probe_in_flight = False
        if threshold <= 0 or not counts_as_failure(exc):
            if b.state == STATE_HALF_OPEN:
                b.state = STATE_CLOSED
                b.consecutive_failures = 0
                b.opened_at = None
            return False
        b.consecutive_failures += 1
        if b.state == STATE_HALF_OPEN or b.consecutive_failures >= threshold:
            b.state = STATE_OPEN
            b.opened_at = _clock()
            logger.warning(
                "模型熔断打开 model_id=%s name=%s 连续失败=%s 最近错误=%s: %s",
                model_id, name, b.consecutive_failures, type(exc).__name__, str(exc)[:200],
            )
        return True


def status() -> list[dict]:
    """非 closed 的熔断器；open 的由系统状态接口放进 degraded。"""
    now = _clock()
    out = []
    with _lock:
        for b in _registry.values():
            if b.state == STATE_CLOSED:
                continue
            out.append({
                "model_id": b.model_id,
                "name": b.name,
                "state": b.state,
                "consecutive_failures": b.consecutive_failures,
                "opened_at": datetime.fromtimestamp(b.opened_at, tz=timezone.utc).isoformat() if b.opened_at else None,
                "retry_after_seconds": _retry_after(b, now) if b.state == STATE_OPEN else 0,
            })
    return out


def reset(model_id: int | None = None) -> None:
    """清空熔断状态（测试用；生产恢复走连通测试）。"""
    with _lock:
        if model_id is None:
            _registry.clear()
        else:
            _registry.pop(model_id, None)
