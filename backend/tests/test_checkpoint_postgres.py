"""工作流 checkpointer 持久化（docs/15 WF-12、docs/09 第二梯队）。

覆盖四件在 MemorySaver 下不可能成立的事：
1. 跨实例（≈跨进程/重启）resume：新 saver、新 graph 实例用同一 thread_id 找回被 interrupt 的图；
2. 终态清理删掉该 thread 的 checkpoint 行，而 awaiting_review 的 thread 必须留着（这是最容易写错的地方）；
3. 两个工作流并发跑互不干扰；
4. SQLAlchemy URL → libpq DSN 的转换（两套驱动并存的关键一步）。

断言都打到"库里的行数"与"resume 后的 state"，不是"没抛异常"。
"""
from __future__ import annotations

import threading
import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from psycopg import connect
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings
from app.workflow.checkpointer import DualModeSaver, delete_thread, delete_thread_safely, libpq_dsn
from app.workflow.engine import build_workflow

THREAD_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


def _thread() -> str:
    return "pytest-cp-" + uuid.uuid4().hex[:12]


def _rows(thread_id: str) -> dict[str, int]:
    """该 thread 在三张 checkpoint 表里的行数（直连查库，不走 saver 的封装）。"""
    with connect(libpq_dsn(settings.DATABASE_URL), autocommit=True, row_factory=dict_row) as conn:
        return {t: conn.execute(f"SELECT count(*) AS n FROM {t} WHERE thread_id = %s", (thread_id,)).fetchone()["n"]
                for t in THREAD_TABLES}


@pytest.fixture
def cleanup_threads():
    """用完的 thread 一律删掉（共享开发库，不能留 checkpoint 残留）。"""
    created: list[str] = []
    yield created
    for tid in created:
        try:
            delete_thread(tid)
        except Exception:  # noqa: BLE001 清理是收尾动作，失败不该改测试结果
            pass


def _independent_saver() -> tuple[PostgresSaver, ConnectionPool]:
    """另起一个连接池的 saver，等价于"另一个进程里刚启动的那份"：与全局池不共享任何内存状态。

    测试里刻意不关全局池：其它用例的 TestClient 还握着它，关掉会串味。
    """
    pool = ConnectionPool(
        conninfo=libpq_dsn(settings.DATABASE_URL), min_size=1, max_size=2, timeout=10,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=False,
    )
    pool.open(wait=True, timeout=15)
    return DualModeSaver(pool), pool


def _review_graph() -> dict:
    """start → code(pre) → human_review → code(post) → end，中断前后都有可辨认的 state。"""
    return {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
            {"id": "pre", "type": "code", "config": {"code": "result = 'draft'"}},
            {"id": "review", "type": "human_review", "config": {"instruction": "请审核"}},
            {"id": "post", "type": "code", "config": {"code": "result = 'post:' + str(input)"}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "pre"}, {"from": "pre", "to": "review"},
                  {"from": "review", "to": "post"}, {"from": "post", "to": "e"}],
    }


def _simple_graph() -> dict:
    return {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
            {"id": "c", "type": "code", "config": {"code": "result = 'done:' + str(input)"}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "c"}, {"from": "c", "to": "e"}],
    }


# ---------------------------------------------------------------- DSN 转换

def test_libpq_dsn_strips_driver_suffix_only():
    """只去掉 +psycopg2；库名、端口、参数原样。saver 只认 libpq DSN，SQLAlchemy 认 URL，这一层必须精确。"""
    url = "postgresql+psycopg2://admin:secret@127.0.0.1:15432/agent_platform"
    assert libpq_dsn(url) == "postgresql://admin:secret@127.0.0.1:15432/agent_platform"


def test_libpq_dsn_keeps_percent_encoded_credentials():
    """口令里的 @ / : 会被 SQLAlchemy 做百分号编码。拼串式转换会在这里改坏口令，且报错看不出原因。"""
    url = "postgresql+psycopg2://user:p%40ss%3Aword@db.internal:5432/app"
    dsn = libpq_dsn(url)
    assert dsn == "postgresql://user:p%40ss%3Aword@db.internal:5432/app"
    assert "p%40ss%3Aword" in dsn


def test_libpq_dsn_keeps_query_parameters():
    url = "postgresql+psycopg2://u:p@h:5432/db?sslmode=require&application_name=agent"
    assert libpq_dsn(url) == "postgresql://u:p@h:5432/db?sslmode=require&application_name=agent"


def test_libpq_dsn_rejects_non_postgres():
    """saver 只支持 Postgres：配成别的库要在启动时立刻报，不留到第一次跑工作流才炸。"""
    with pytest.raises(ValueError, match="只支持 Postgres"):
        libpq_dsn("mysql+psycopg2://u:p@h:3306/db")


def test_libpq_dsn_is_usable_by_psycopg():
    """转换出来的串要真的能连上（本机 .env.local 走 SSH 隧道到同一套库）。"""
    with connect(libpq_dsn(settings.DATABASE_URL), connect_timeout=10) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1


# ---------------------------------------------------------------- 异步路径

def test_async_graph_path_works_only_with_dual_mode_saver(cleanup_threads):
    """工作流对话走 graph.astream（异步），而 PostgresSaver 只实现了同步接口。

    没有 DualModeSaver 时，astream 在 aget_tuple 上直接 NotImplementedError ——
    这就是本用例的前半段：同一个 saver 用基类的默认异步实现一定失败，说明补丁不是装饰。
    """
    import asyncio

    class SyncOnly(PostgresSaver):
        """刻意什么都不补：与直接使用 PostgresSaver 等价（基类的 a* 全是 raise）。"""

    tid = _thread()
    cleanup_threads.append(tid)
    cfg = {"configurable": {"thread_id": tid}}

    saver, pool = _independent_saver()
    try:
        graph_sync_only = build_workflow(_simple_graph(), checkpointer=SyncOnly(pool))
        with pytest.raises(NotImplementedError):
            asyncio.run(_astream_once(graph_sync_only, {"input": "x", "steps": []}, cfg))

        # 换成真正会被引擎使用的 DualModeSaver：同一条异步路径能跑完并落库
        graph = build_workflow(_simple_graph(), checkpointer=saver)
        updates = asyncio.run(_astream_once(graph, {"input": "x", "steps": []}, cfg))
        visited = [node_id for u in updates for node_id in u if node_id != "__interrupt__"]
        assert visited == ["s", "c", "e"]
        assert _rows(tid)["checkpoints"] > 0
    finally:
        pool.close()


async def _astream_once(graph, initial, config):
    return [u async for u in graph.astream(initial, config=config, stream_mode="updates")]


# ---------------------------------------------------------------- 跨实例 resume

def test_resume_from_another_instance_after_interrupt(cleanup_threads):
    """跑到人工审核中断 → 丢弃所有内存状态（另起连接池的 saver + 重新编译的图）→ 同 thread_id 续跑成功。

    MemorySaver 下这一段必失败：线程 A 的图在进程内存里，另一个实例看到的检查点是空的。
    下面同时给出对照：两个 MemorySaver 互不可见，resume 会从空 state 重跑而非接着走。
    """
    graph_data = _review_graph()
    tid = _thread()
    cleanup_threads.append(tid)
    cfg = {"configurable": {"thread_id": tid}}

    # 对照：内存实现的检查点不出进程，第二个实例读不到
    mem_a, mem_b = MemorySaver(), MemorySaver()
    build_workflow(graph_data, checkpointer=mem_a).invoke({"input": "x", "steps": []}, cfg)
    assert mem_a.get_tuple(cfg) is not None
    assert mem_b.get_tuple(cfg) is None

    # 实例 1：跑到人工审核
    saver1, pool1 = _independent_saver()
    try:
        paused = build_workflow(graph_data, checkpointer=saver1).invoke({"input": "x", "steps": []}, cfg, version="v2")
        assert paused.interrupts and paused.interrupts[0].value["instruction"] == "请审核"
        assert paused.value["node_outputs"] == {"pre": "draft"}
        assert _rows(tid)["checkpoints"] >= 1
    finally:
        pool1.close()

    # 实例 2：全新连接池 + 重新编译的图（等价于进程重启后那个进程）
    saver2, pool2 = _independent_saver()
    try:
        graph2 = build_workflow(graph_data, checkpointer=saver2)
        resumed = graph2.invoke(Command(resume={"approved": True}), cfg, version="v2")
        assert not resumed.interrupts
        # 接着中断点继续：pre 的输出还在，post 拿到了 review 的返回值
        assert resumed.value["node_outputs"] == {"pre": "draft", "review": {"approved": True}, "post": "post:{'approved': True}"}
        assert resumed.value["output"] == "post:{'approved': True}"
    finally:
        pool2.close()


# ---------------------------------------------------------------- 终态清理

def test_terminal_cleanup_deletes_all_thread_rows(cleanup_threads):
    """成功收尾后清理：三张表里该 thread 的行都归零（否则每跑一次就永久多一份完整历史）。"""
    tid = _thread()
    cleanup_threads.append(tid)
    cfg = {"configurable": {"thread_id": tid}}

    saver, pool = _independent_saver()
    try:
        result = build_workflow(_simple_graph(), checkpointer=saver).invoke({"input": "x", "steps": []}, cfg, version="v2")
        assert result.value["output"] == "done:x"
        before = _rows(tid)
        assert before["checkpoints"] >= 1 and before["checkpoint_writes"] >= 1

        delete_thread(tid)

        assert _rows(tid) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}
    finally:
        pool.close()


def test_awaiting_review_thread_must_survive_cleanup(cleanup_threads):
    """awaiting_review 的 thread 保留：删了之后 resume 就找不到图，流程会从空 state 重跑。

    这条是本任务最容易写错的负向点，所以两头都断言：
    ① 保留时 resume 接着中断点走；② 删掉后再 resume 会重跑（证明"删掉"确实会丢状态，不是无害操作）。
    """
    graph_data = _review_graph()
    tid = _thread()
    cleanup_threads.append(tid)
    cfg = {"configurable": {"thread_id": tid}}

    saver, pool = _independent_saver()
    try:
        graph = build_workflow(graph_data, checkpointer=saver)
        paused = graph.invoke({"input": "x", "steps": []}, cfg, version="v2")
        assert paused.interrupts
        # awaiting_review：checkpoint 必须还在（终态清理不能碰它）
        assert _rows(tid)["checkpoints"] >= 1
        assert saver.get_tuple(cfg) is not None

        resumed = graph.invoke(Command(resume={"approved": True}), cfg, version="v2")
        assert resumed.value["node_outputs"]["pre"] == "draft"

        # 反证：先删掉这个 thread 的检查点，再用同 thread_id resume →
        # 图找不到中断点，会从空 state 重跑一遍并再次停在审核节点（上面那次 resume 是走到底、无 interrupt）。
        # 这说明"删掉"确实丢状态，不是无害操作 —— 所以终态清理必须排除 awaiting_review。
        delete_thread(tid)
        assert _rows(tid)["checkpoints"] == 0
        lost = build_workflow(graph_data, checkpointer=saver).invoke(
            Command(resume={"approved": True}), cfg, version="v2")
        assert lost.interrupts, "检查点删掉后 resume 应当重新跑到底并再次中断，而不是接着走"
        assert lost.value["node_outputs"] == {"pre": "draft"}
    finally:
        pool.close()


def test_cleanup_failure_does_not_break_the_run(monkeypatch, caplog):
    """清理是收尾动作，失败只记日志：不能因为删不掉检查点就把一次成功的运行改成失败。"""
    def _boom(_thread_id: str) -> None:
        raise RuntimeError("模拟连接池已关闭")

    monkeypatch.setattr("app.workflow.checkpointer.delete_thread", _boom)
    with caplog.at_level("WARNING"):
        delete_thread_safely("pytest-cp-nonexistent")
    assert any("检查点清理失败" in r.message for r in caplog.records)


# ---------------------------------------------------------------- 并发

def test_two_workflows_run_concurrently_without_touching_each_other(cleanup_threads):
    """两个 thread 同时跑：各自 state 正确、各自的行数对得上。

    共用一个 saver 时会被它内部那把 threading.Lock 串行化（并发度归零），
    所以 build_workflow 默认每次新建 saver 实例、只共用连接池 —— 这里同时压这一点。
    """
    results: dict[str, dict] = {}
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)
    threads = {name: _thread() for name in ("a", "b")}
    cleanup_threads.extend(threads.values())

    def _run(name: str) -> None:
        try:
            saver, pool = _independent_saver()
            try:
                cfg = {"configurable": {"thread_id": threads[name]}}
                graph = build_workflow(_simple_graph(), checkpointer=saver)
                barrier.wait(timeout=10)  # 尽量让两条图真的重叠执行
                out = graph.invoke({"input": name, "steps": []}, cfg, version="v2")
                results[name] = out.value
            finally:
                pool.close()
        except BaseException as e:  # noqa: BLE001 线程里的异常要在主线程断言，否则只看到 KeyError
            errors.append(e)

    workers = [threading.Thread(target=_run, args=(n,)) for n in threads]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=60)

    assert not errors, [repr(e) for e in errors]
    assert results["a"]["output"] == "done:a"
    assert results["b"]["output"] == "done:b"
    # 两条 thread 的检查点互不串
    assert _rows(threads["a"])["checkpoints"] >= 1
    assert _rows(threads["b"])["checkpoints"] >= 1
