"""工作流对外运行契约（docs/15 WF-05 / FR-078，2026-11-18）。

四件事：
1. `response_mode=async`：建完运行记录立刻 202 + run_id，后台继续跑；同一个 Key 能轮询到 success。
2. `response_mode=blocking` 超时：只放弃等待、不取消执行，返回 202 + run_id，后台照样跑完。
3. 取消：running → cancelled 且之后不再新增节点日志；已 success → 409；重复取消已取消 → 200 且状态不变。
4. Key 隔离：Key B 查 / 取消 Key A 发起的运行都 404（不暴露存在性）。

慢节点用代码节点里的 time.sleep 造（沙箱子进程，默认 30 秒超时，sleep 不耗 CPU）。
"""

import time

import pytest

from app.config import settings
from app.db.models import Run, RunNode
from app.db.session import SessionLocal
from app.services import workflow_service
from app.workflow import cancel as workflow_cancel
from app.workflow import runner as workflow_runner
from tests.conftest import publish_workflow

# start → 慢代码节点 → end：跑一次约 SLOW_S 秒，足够在返回之后观察到 running
SLOW_S = 1.5


def _graph(sleep: float = SLOW_S, extra_slow: bool = False) -> dict:
    nodes = [
        {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
        {"id": "slow", "type": "code", "config": {"code": f"import time; time.sleep({sleep}); result = 'ok'"}},
    ]
    edges = [{"from": "s", "to": "slow"}]
    if extra_slow:
        # 第二个慢节点：取消发生在第一个节点执行期间，第二个节点开始前应当命中取消标记
        nodes.append({"id": "slow2", "type": "code", "config": {"code": f"import time; time.sleep({sleep}); result = 'ok2'"}})
        edges.append({"from": "slow", "to": "slow2"})
    nodes.append({"id": "e", "type": "end", "config": {}})
    edges.append({"from": nodes[-2]["id"], "to": "e"})
    return {"nodes": nodes, "edges": edges}


def _make_workflow(client, auth_headers, name: str, graph: dict | None = None) -> int:
    """建并发布（运行只读线上版本，未发布一律 403）。"""
    res = client.post("/api/v1/workflows", headers=auth_headers,
                      json={"name": name, "description": "", "graph": graph or _graph()})
    assert res.status_code == 200, res.text
    wid = res.json()["id"]
    publish_workflow(client, auth_headers, wid)
    return wid


def _make_key(client, auth_headers, wid: int, name: str) -> dict:
    res = client.post("/api/v1/api-keys", headers=auth_headers,
                      json={"name": name, "quota": 1000, "workflow_ids": [wid]})
    assert res.status_code == 200, res.text
    return res.json()


def _bearer(key: str) -> dict:
    return {"Authorization": "Bearer " + key}


def _wait_status(client, headers, wid: int, run_id: int, want: str, timeout: float = 30.0) -> dict:
    """轮询到指定终态（超时抛断言，避免用例无限挂住）。"""
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        r = client.get(f"/api/v1/workflows/{wid}/runs/{run_id}", headers=headers)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] == want:
            return last
        time.sleep(0.2)
    raise AssertionError(f"等待 {want} 超时，当前 {last.get('status')}")


def _node_count(run_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(RunNode).filter(RunNode.run_id == run_id).count()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_cancel_marks():
    """取消标记是进程内全局状态：用例之间必须隔离，否则上一条的标记会误伤下一条。"""
    workflow_cancel.reset()
    yield
    workflow_cancel.reset()


# ---------- async：立刻 202，同一个 Key 轮询到 success ----------

def test_async_returns_202_immediately_and_key_polls_to_success(client, auth_headers):
    wid = _make_workflow(client, auth_headers, "pytest-wf-async")
    key = _make_key(client, auth_headers, wid, "pytest-wf-async-key")
    try:
        started = time.monotonic()
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=_bearer(key["key"]),
                        json={"inputs": {"input": "x"}, "response_mode": "async"})
        elapsed = time.monotonic() - started
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "running" and isinstance(body["run_id"], int)
        # 慢节点要跑 SLOW_S 秒，202 必须明显早于它（同步等待会 >= SLOW_S）
        assert elapsed < SLOW_S, f"async 没有立即返回：{elapsed:.2f}s"

        done = _wait_status(client, _bearer(key["key"]), wid, body["run_id"], "success")
        assert done["id"] == body["run_id"]
        assert done["finished_at"] is not None
        # 后台执行真的跑完了整张图（节点日志是引擎写的，能证明执行发生在后台线程而不是请求线程）
        assert _node_count(body["run_id"]) >= 2
    finally:
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_default_response_mode_is_blocking(client, auth_headers):
    """默认值必须是 blocking：存量调用方（前端运行弹窗、既有测试）都按同步返回解析结果。"""
    wid = _make_workflow(client, auth_headers, "pytest-wf-default-blocking",
                         graph={"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "e", "type": "end", "config": {}}],
                                "edges": [{"from": "s", "to": "e"}]})
    try:
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"inputs": {}})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "success"
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


# ---------- blocking 超时：只放弃等待，不取消执行 ----------

def test_blocking_timeout_returns_202_and_background_finishes(client, auth_headers):
    wid = _make_workflow(client, auth_headers, "pytest-wf-blocking-timeout")
    old = settings.WORKFLOW_BLOCKING_TIMEOUT_S
    # 0 秒 = 立刻判定"等不及"，等价于生产里流程比 WORKFLOW_BLOCKING_TIMEOUT_S 慢的情况
    settings.WORKFLOW_BLOCKING_TIMEOUT_S = 0
    try:
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers,
                        json={"inputs": {"input": "x"}, "response_mode": "blocking"})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "running"
        run_id = body["run_id"]

        # 关键：超时**不取消**任务 —— 运行记录最终必须自己跑成 success，而不是停在 running / failed
        done = _wait_status(client, auth_headers, wid, run_id, "success")
        assert done["finished_at"] is not None
        assert _node_count(run_id) >= 2
    finally:
        settings.WORKFLOW_BLOCKING_TIMEOUT_S = old
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


# ---------- 取消 ----------

def test_cancel_running_stops_further_nodes(client, auth_headers):
    wid = _make_workflow(client, auth_headers, "pytest-wf-cancel", graph=_graph(sleep=1.0, extra_slow=True))
    try:
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers,
                        json={"inputs": {"input": "x"}, "response_mode": "async"})
        assert r.status_code == 202, r.text
        run_id = r.json()["run_id"]
        # 等第一个慢节点确实开始（有节点日志）再取消，否则取消可能早于执行，测不到"节点开始前命中"
        deadline = time.monotonic() + 10
        while _node_count(run_id) < 1 and time.monotonic() < deadline:
            time.sleep(0.1)

        c = client.post(f"/api/v1/workflows/{wid}/runs/{run_id}/cancel", headers=auth_headers)
        assert c.status_code == 200, c.text
        assert c.json() == {"run_id": run_id, "status": "cancelled"}

        nodes_at_cancel = _node_count(run_id)
        time.sleep(2.5)  # 超过两个慢节点的总时长：若取消没生效，这里会多出节点日志
        assert _node_count(run_id) == nodes_at_cancel, "取消后仍在新增节点日志"

        detail = client.get(f"/api/v1/workflows/{wid}/runs/{run_id}", headers=auth_headers).json()
        assert detail["status"] == "cancelled"
        assert detail["finished_at"] is not None
        assert detail["latency_ms"] > 0  # 取消也要算耗时（否则监控页显示成 0 耗时）
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_cancel_finished_run_is_409(client, auth_headers):
    wid = _make_workflow(client, auth_headers, "pytest-wf-cancel-409",
                         graph={"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "e", "type": "end", "config": {}}],
                                "edges": [{"from": "s", "to": "e"}]})
    try:
        run = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"inputs": {}}).json()
        assert run["status"] == "success"
        c = client.post(f"/api/v1/workflows/{wid}/runs/{run['run_id']}/cancel", headers=auth_headers)
        assert c.status_code == 409, c.text
        assert "无法取消" in c.json()["detail"]
        # 已结束的运行状态不能被改
        assert client.get(f"/api/v1/workflows/{wid}/runs/{run['run_id']}", headers=auth_headers).json()["status"] == "success"
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_cancel_twice_is_idempotent_200(client, auth_headers):
    wid = _make_workflow(client, auth_headers, "pytest-wf-cancel-twice", graph=_graph(sleep=1.0, extra_slow=True))
    try:
        run = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers,
                          json={"inputs": {"input": "x"}, "response_mode": "async"}).json()
        first = client.post(f"/api/v1/workflows/{wid}/runs/{run['run_id']}/cancel", headers=auth_headers)
        assert first.status_code == 200, first.text
        second = client.post(f"/api/v1/workflows/{wid}/runs/{run['run_id']}/cancel", headers=auth_headers)
        assert second.status_code == 200, second.text
        assert second.json() == {"run_id": run["run_id"], "status": "cancelled"}
        after_first = client.get(f"/api/v1/workflows/{wid}/runs/{run['run_id']}", headers=auth_headers).json()
        assert after_first["status"] == "cancelled"
        assert after_first["finished_at"] is not None
        # 第二次取消是幂等的：不改状态，也不改终态时间（否则每次重试都把完成时间往后推）
        after_second = client.get(f"/api/v1/workflows/{wid}/runs/{run['run_id']}", headers=auth_headers).json()
        assert after_second["status"] == "cancelled"
        assert after_second["finished_at"] == after_first["finished_at"]
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_cancel_unknown_run_is_404(client, auth_headers):
    wid = _make_workflow(client, auth_headers, "pytest-wf-cancel-404")
    try:
        c = client.post(f"/api/v1/workflows/{wid}/runs/999999999/cancel", headers=auth_headers)
        assert c.status_code == 404, c.text
        g = client.get(f"/api/v1/workflows/{wid}/runs/999999999", headers=auth_headers)
        assert g.status_code == 404, g.text
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


# ---------- Key 隔离：Key B 查 / 取消 Key A 发起的运行都 404 ----------

def test_other_key_cannot_get_or_cancel_run(client, auth_headers):
    wid = _make_workflow(client, auth_headers, "pytest-wf-key-isolation", graph=_graph(sleep=1.0, extra_slow=True))
    key_a = _make_key(client, auth_headers, wid, "pytest-wf-key-a")
    key_b = _make_key(client, auth_headers, wid, "pytest-wf-key-b")
    try:
        run = client.post(f"/api/v1/workflows/{wid}/run", headers=_bearer(key_a["key"]),
                          json={"inputs": {"input": "x"}, "response_mode": "async"}).json()
        run_id = run["run_id"]

        # Key B 拿到了同一个 run_id 也查不到、取消不了（404 不暴露存在性）
        g = client.get(f"/api/v1/workflows/{wid}/runs/{run_id}", headers=_bearer(key_b["key"]))
        assert g.status_code == 404, g.text
        assert g.json()["detail"] == "运行记录不存在"
        c = client.post(f"/api/v1/workflows/{wid}/runs/{run_id}/cancel", headers=_bearer(key_b["key"]))
        assert c.status_code == 404, c.text

        # Key A 自己能查
        own = client.get(f"/api/v1/workflows/{wid}/runs/{run_id}", headers=_bearer(key_a["key"]))
        assert own.status_code == 200, own.text
        assert own.json()["api_key_id"] == key_a["id"]

        # 界面（JWT）不受 Key 隔离限制，能查也能取消
        assert client.get(f"/api/v1/workflows/{wid}/runs/{run_id}", headers=auth_headers).status_code == 200
        assert client.post(f"/api/v1/workflows/{wid}/runs/{run_id}/cancel", headers=auth_headers).status_code == 200
    finally:
        client.delete(f"/api/v1/api-keys/{key_a['id']}", headers=auth_headers)
        client.delete(f"/api/v1/api-keys/{key_b['id']}", headers=auth_headers)
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


# ---------- 有界并发：满了 429，且不留下没人执行的 running 记录 ----------

def test_concurrency_limit_returns_429_without_orphan_run(client, auth_headers):
    wid = _make_workflow(client, auth_headers, "pytest-wf-concurrency", graph=_graph(sleep=2.0))
    old = settings.WORKFLOW_MAX_CONCURRENCY
    settings.WORKFLOW_MAX_CONCURRENCY = 1
    workflow_runner.reset()  # 按新上限重建池与信号量
    try:
        first = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers,
                            json={"inputs": {"input": "x"}, "response_mode": "async"})
        assert first.status_code == 202, first.text

        second = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers,
                             json={"inputs": {"input": "x"}, "response_mode": "async"})
        assert second.status_code == 429, second.text
        assert "并发" in second.json()["detail"]

        # 429 在建运行记录之前拒绝：库里只应有第一条（否则调用方会以为第二条在跑）
        db = SessionLocal()
        try:
            count = db.query(Run).filter(Run.workflow_id == wid).count()
        finally:
            db.close()
        assert count == 1, f"429 仍然建了运行记录（{count} 条）"

        _wait_status(client, auth_headers, wid, first.json()["run_id"], "success")
    finally:
        settings.WORKFLOW_MAX_CONCURRENCY = old
        workflow_runner.reset()
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


# ---------- 引擎侧：取消标记命中后不再写节点日志（纯函数级） ----------

def test_engine_guard_raises_before_node_starts():
    """_guarded 包装必须抛在节点函数之前：命中取消时连节点日志都不能写（这是"不再新增节点日志"的依据）。"""
    from app.workflow import engine

    called = []
    guarded = engine._guarded(424242, lambda state: called.append(state) or {"steps": []})
    workflow_cancel.mark(424242)
    try:
        with pytest.raises(workflow_cancel.RunCancelled):
            guarded({})
        assert called == [], "取消后节点函数仍被执行"
    finally:
        workflow_cancel.discard(424242)

    # 未取消时正常透传
    assert guarded({}) == {"steps": []}
    assert len(called) == 1
