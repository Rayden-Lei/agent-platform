"""只读接口不能有副作用：状态接口不得顺手启动调度器。

扫描发现 `GET /system/status`（以及内部调它的 `GET /stats/overview`）会走
`system_service._scheduler_status()` → `scheduler.get_scheduler()`，而后者是懒启动的：
一个探活请求就会拉起后台线程、把库里所有启用任务注册进来。

后果不是性能问题，而是**副作用藏在读接口里**：
- 测试里本该由 lifespan 控制的调度器被某个读用例意外启动，之后所有用例都在有调度器的进程里跑；
- 哪天要"关掉调度器跑单进程"，一个探活请求就把它拉起来了。

本文件用 peek_scheduler 的存在当作判据：调用状态接口前后，调度器实例都必须保持 None。
"""
from __future__ import annotations

import pytest

from app.core import scheduler as scheduler_module


@pytest.fixture(autouse=True)
def _restore_scheduler():
    """用例结束后把全局调度器恢复成用例开始前的样子，避免污染其它用例。"""
    before = scheduler_module.peek_scheduler()
    yield
    after = scheduler_module.peek_scheduler()
    if after is not None and after is not before:
        # 本用例期间被意外启动了：停掉并复位，让断言失败但不拖累后续用例
        try:
            after.shutdown(wait=False)
        except Exception:
            pass
        scheduler_module._scheduler = before


def test_peek_does_not_start_scheduler():
    """peek 是只读的：调度器没启动时返回 None，且调用后仍然是 None。"""
    scheduler_module._scheduler = None
    assert scheduler_module.peek_scheduler() is None
    assert scheduler_module.peek_scheduler() is None
    assert scheduler_module._scheduler is None


def test_system_status_does_not_start_scheduler(client, auth_headers):
    """打状态接口不能把调度器拉起来 —— 这是本文件存在的理由。"""
    scheduler_module._scheduler = None
    res = client.get("/api/v1/system/status", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert scheduler_module.peek_scheduler() is None, "只读状态接口不该启动后台调度线程"


def test_stats_overview_does_not_start_scheduler(client, auth_headers):
    """工作台概览同样：它内部也调 get_system_status。"""
    scheduler_module._scheduler = None
    res = client.get("/api/v1/stats/overview", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert scheduler_module.peek_scheduler() is None, "只读统计接口不该启动后台调度线程"


def test_scheduler_status_reports_not_running_when_absent(client, auth_headers):
    """调度器没启动时，状态里要如实说 running=False、registered=0，而不是硬编或报错。"""
    scheduler_module._scheduler = None
    body = client.get("/api/v1/system/status", headers=auth_headers).json()
    sched = body.get("scheduler") or {}
    assert sched.get("running") is False
    assert sched.get("registered_jobs") == 0
