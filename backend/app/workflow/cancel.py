"""工作流运行的取消标记（docs/15 WF-05，FR-078）。

取消是**协作式**的：接口把 runs 行改成 cancelled（带前置条件的 UPDATE），同时在这里打一个进程内标记；
引擎在**每个节点开始前**查一次标记，命中就抛出 RunCancelled，不再写新的节点日志、不再往下跑。

为什么是进程内 set 而不是只查库：引擎在节点边界要判一次，若每次查库就是每个节点多一次往返；
更重要的是"取消"发生在另一个线程，只靠库里那一行，正在跑的图看不到任何变化。
为什么还要写库：进程重启、或多 worker 部署时，库里的 cancelled 才是唯一可靠的终态（进程内 set 会丢）。

两个方向的脏数据都要收：运行结束（无论何种结局）必须 discard，否则这个进程的 set 会一直留着
已经结束的 run_id（长期运行的服务里就是内存泄漏）。
"""

import threading

from app.core.exceptions import BizError


class RunCancelled(Exception):
    """运行已被取消：引擎在节点开始前抛出，execute_workflow 据此把运行收尾为 cancelled（不是 failed）。

    刻意不继承 BizError：它不是"调用方传错了参数"，而是外部并发发起的终止信号，
    不该被任何按 BizError 判 400 的分支接住。
    """


_lock = threading.Lock()
_cancelled: set[int] = set()


def mark(run_id: int) -> None:
    """标记该运行已取消（接口层在把 runs 行改成 cancelled 之后调用）。"""
    with _lock:
        _cancelled.add(int(run_id))


def is_cancelled(run_id: int | None) -> bool:
    """是否已取消。run_id 为空（试运行不建运行记录）时恒为 False。"""
    if not run_id:
        return False
    with _lock:
        return int(run_id) in _cancelled


def discard(run_id: int | None) -> None:
    """运行结束（success / failed / cancelled / awaiting_review）后清掉标记，避免无限累积。"""
    if not run_id:
        return
    with _lock:
        _cancelled.discard(int(run_id))


def reset() -> None:
    """清空全部标记。只给测试用：多个用例共用一个进程，上一条用例的取消不该影响下一条。"""
    with _lock:
        _cancelled.clear()


def raise_if_cancelled(run_id: int | None) -> None:
    """节点开始前的统一检查点：命中即抛 RunCancelled。"""
    if is_cancelled(run_id):
        raise RunCancelled(f"运行 {run_id} 已被取消")
