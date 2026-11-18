"""工作流执行的有界线程池（docs/15 WF-05，FR-078）。

为什么要有界：工作流执行是**长任务**（模型节点、HTTP 节点、代码节点），一次请求可能跑几分钟。
此前 run_workflow 用 asyncio.to_thread，实际落在 anyio 的默认线程池（40 线程）上 ——
那个池同时也是所有 `def` 路由的运行时，几十个并发工作流就能把整站拖慢（与 app/rag/pipeline.py 同一个教训）。

两道闸：
- ThreadPoolExecutor(max_workers=WORKFLOW_MAX_CONCURRENCY)：进程内单例，与请求线程池彻底隔离；
- BoundedSemaphore 同数量：**判满**用信号量而不是看队列长度，满了立刻 429 告诉调用方，
  而不是让请求排到天荒地老再超时（排队的运行在调用方看来就是"没反应"）。

槽的释放必须在 worker 的 finally 里，且与"提交失败"分支互斥 —— 两处都放会触发
BoundedSemaphore 的 ValueError（释放超过初始值），只放一处漏了则这个进程的并发额度永久少一个。
acquire() 把信号量对象返回给调用方、由它一路传给 submit()，而不是在 release 时再去取单例：
测试改配置后 reset() 会换掉单例，此时旧任务结束时若按新单例释放，就会释放一个自己没占过的槽。
"""

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from app.config import settings
from app.core.exceptions import BizError

logger = logging.getLogger(__name__)

_pool_lock = threading.Lock()
_pool: "ThreadPoolExecutor | None" = None
_slot_lock = threading.Lock()
_slots: "threading.BoundedSemaphore | None" = None


def _executor() -> "ThreadPoolExecutor":
    """工作流执行专用线程池（进程内单例）。"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadPoolExecutor(
                    max_workers=max(1, settings.WORKFLOW_MAX_CONCURRENCY),
                    thread_name_prefix="workflow",
                )
    return _pool


def _semaphore() -> "threading.BoundedSemaphore":
    """并发槽（与线程池同数量）。"""
    global _slots
    if _slots is None:
        with _slot_lock:
            if _slots is None:
                _slots = threading.BoundedSemaphore(max(1, settings.WORKFLOW_MAX_CONCURRENCY))
    return _slots


def acquire() -> "threading.BoundedSemaphore":
    """占一个并发槽并返回它；已满抛 BizError(429)。

    必须在**建运行记录之前**调用：满了就不该留下一条没人执行的 running 记录
    （那条记录会让调用方以为"提交成功在跑"，实际永远不会结束）。
    """
    sem = _semaphore()
    if not sem.acquire(blocking=False):
        limit = max(1, settings.WORKFLOW_MAX_CONCURRENCY)
        raise BizError(429, f"工作流并发已达上限（{limit}），请稍后重试")
    return sem


def release(sem: "threading.BoundedSemaphore") -> None:
    """归还一个并发槽（只由 submit 的失败分支或 worker 的 finally 调用一次）。"""
    sem.release()


def submit(sem: "threading.BoundedSemaphore", fn, *args) -> Future:
    """把已占槽（sem）的任务丢进池子；槽在任务结束时自动释放。"""
    def _wrapped():
        try:
            return fn(*args)
        finally:
            sem.release()

    try:
        return _executor().submit(_wrapped)
    except BaseException:
        # 线程池已关闭等极端情况：槽还没交给 worker，必须在这里归还，否则永久少一个额度
        sem.release()
        raise


def reset() -> None:
    """丢弃进程内单例（线程池与信号量）。只给测试用：改配置后要重新按新上限建池。

    已在跑的任务各自持有自己的信号量对象（见模块文档），换掉单例不会让它们释放错对象。
    """
    global _pool, _slots
    with _pool_lock:
        old = _pool
        _pool = None
    with _slot_lock:
        _slots = None
    if old is not None:
        old.shutdown(wait=False)
