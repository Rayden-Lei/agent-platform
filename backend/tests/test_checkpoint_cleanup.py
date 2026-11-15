"""三个工作流入口的检查点清理（docs/15 WF-12）。

为什么单独一个文件：清理放错位置的后果都不报错 ——
- 终态不清：checkpoints / checkpoint_blobs / checkpoint_writes 三张表只涨不消，最终撑爆磁盘（本任务要解决的问题）；
- awaiting_review 清了：审批一提交就找不到中断点，流程从空 state 重跑，用户以为审批生效了其实没有。
两者都不会抛异常，只能靠断言"库里的行在不在"。

覆盖三个入口（thread_id 分别是 run.id / test-xxx / run.id）：
1. POST /workflows/{id}/run（同步执行）→ success 清、awaiting_review 留；
2. POST /workflows/test-run（编辑器试跑）→ 无论结果如何都清；
3. 工作流对话（chat_runner.stream_workflow，异步 astream）→ success 清、awaiting_review 留。
"""
from __future__ import annotations

import json
import uuid

import pytest
from psycopg import connect
from psycopg.rows import dict_row

from app.config import settings
from app.db.models import Run
from app.db.session import SessionLocal
from app.workflow.checkpointer import libpq_dsn
from tests.conftest import publish_workflow

TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


def checkpoint_rows(thread_id: str) -> dict[str, int]:
    with connect(libpq_dsn(settings.DATABASE_URL), autocommit=True, row_factory=dict_row) as conn:
        return {t: conn.execute(f"SELECT count(*) AS n FROM {t} WHERE thread_id = %s", (thread_id,)).fetchone()["n"]
                for t in TABLES}


def _start_codes_end(action: str = "success") -> dict:
    """start → code → end 的最小图（代码节点用沙箱，不碰外部服务）。"""
    return {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
            {"id": "c", "type": "code", "config": {"code": f"result = '{action}:' + str(input)"}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "c"}, {"from": "c", "to": "e"}],
    }


def _review_graph() -> dict:
    """start → code → human_review → end：停在审核节点，运行记录应为 awaiting_review。"""
    return {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
            {"id": "c", "type": "code", "config": {"code": "result = 'draft'"}},
            {"id": "r", "type": "human_review", "config": {"instruction": "请审核"}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "c"}, {"from": "c", "to": "r"}, {"from": "r", "to": "e"}],
    }


@pytest.fixture
def make_published_workflow(client, auth_headers):
    """建 + 发布一个工作流，用完删掉（运行记录随 CASCADE 走）。"""
    created: list[int] = []

    def _make(graph: dict) -> int:
        r = client.post("/api/v1/workflows", headers=auth_headers, json={
            "name": "pytest-cp-wf-" + uuid.uuid4().hex[:6], "description": "检查点清理", "graph": graph})
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        created.append(wid)
        publish_workflow(client, auth_headers, wid)
        return wid

    yield _make
    for wid in created:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


# --------------------------------------------------------------- 1. 同步执行入口

def test_successful_run_deletes_its_checkpoints(client, auth_headers, make_published_workflow):
    """成功收尾后该 thread 的三张表都归零。"""
    wid = make_published_workflow(_start_codes_end())
    body = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"inputs": {"input": "hi"}}).json()
    assert body["status"] == "success", body
    assert checkpoint_rows(str(body["run_id"])) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}


def test_awaiting_review_run_keeps_its_checkpoints(client, auth_headers, make_published_workflow):
    """停在人工审核的运行，检查点必须留着（否则审批时 resume 找不到图）。"""
    wid = make_published_workflow(_review_graph())
    body = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"inputs": {"input": "hi"}}).json()
    assert body["status"] == "awaiting_review", body
    rows = checkpoint_rows(str(body["run_id"]))
    assert rows["checkpoints"] >= 1, "awaiting_review 的运行必须保留检查点，resume 靠它找回被 interrupt 的图"

    # 审批续跑后走到终态，这时才该清
    resumed = client.post(f"/api/v1/workflows/{wid}/runs/{body['run_id']}/resume",
                          headers=auth_headers, json={"decision": {"approved": True}})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "success"
    assert checkpoint_rows(str(body["run_id"]))["checkpoints"] == 0, "续跑到终态后应当清理"


def test_failed_run_deletes_its_checkpoints(client, auth_headers, make_published_workflow):
    """失败的运行同样是终态：不能因为"没成功"就把检查点留在库里。"""
    # 代码节点抛异常 → 节点失败 → 整条运行 failed
    graph = _start_codes_end()
    graph["nodes"][1]["config"]["code"] = "raise ValueError('pytest 故意失败')"
    wid = make_published_workflow(graph)
    body = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"inputs": {"input": "hi"}}).json()
    assert body["status"] == "failed", body
    assert checkpoint_rows(str(body["run_id"])) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}


# --------------------------------------------------------------- 2. 编辑器试跑入口

def test_test_run_always_cleans_its_thread(client, auth_headers):
    """试运行用 test-<uuid> 作 thread_id，成功/中断/失败三种结局都必须清干净。

    它是唯一"没有外部可见终态"的执行路径：没有运行记录、没有 resume 入口，
    所以连中断的预览也不该在库里留检查点。
    """
    run_before = _count_all_checkpoints()

    ok = client.post("/api/v1/workflows/test-run", headers=auth_headers,
                     json={"graph": _start_codes_end(), "inputs": {"input": "hi"}}).json()
    assert ok["status"] == "success", ok

    paused = client.post("/api/v1/workflows/test-run", headers=auth_headers,
                         json={"graph": _review_graph(), "inputs": {"input": "hi"}}).json()
    assert paused["status"] == "awaiting_review", paused

    bad_graph = _start_codes_end()
    bad_graph["nodes"][1]["config"]["code"] = "raise ValueError('pytest 故意失败')"
    failed = client.post("/api/v1/workflows/test-run", headers=auth_headers,
                         json={"graph": bad_graph, "inputs": {"input": "hi"}}).json()
    assert failed["status"] == "failed", failed

    # 只比总数：thread_id 是服务端生成的 uuid，用例拿不到；"跑三次不多出任何行"就是这条断言的全部含义
    assert _count_all_checkpoints() == run_before, "试运行的检查点必须全部清理，否则编辑器点一次就永久多一份"


def _count_all_checkpoints() -> int:
    with connect(libpq_dsn(settings.DATABASE_URL), autocommit=True, row_factory=dict_row) as conn:
        return sum(conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in TABLES)


# --------------------------------------------------------------- 3. 工作流对话入口（异步 astream）

def _events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def _chat(client, headers, workflow_id: int, message: str):
    """工作流对话入口（chat_runner.stream_workflow，异步 astream 路径）。"""
    return client.post(f"/api/v1/workflows/{workflow_id}/chat", headers=headers, json={"message": message})


def test_workflow_chat_success_cleans_checkpoints(client, auth_headers, make_published_workflow):
    """对话跑完（success）后检查点清掉：这是走 graph.astream 的异步路径，最容易漏的一处。"""
    wid = make_published_workflow(_start_codes_end())
    events = _events(_chat(client, auth_headers, wid, "跑一下"))
    assert events and events[-1]["type"] == "done", events[-1:] 
    assert events[-1]["finished_reason"] == "completed"
    run_id = events[-1]["run_id"]
    assert checkpoint_rows(str(run_id)) == {"checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0}


def test_workflow_chat_awaiting_review_keeps_checkpoints(client, auth_headers, make_published_workflow):
    """对话停在人工审核：运行记录与检查点都要留着，运行记录页的 resume 才走得通。"""
    wid = make_published_workflow(_review_graph())
    events = _events(_chat(client, auth_headers, wid, "走到审核"))
    assert events[-1]["finished_reason"] == "interrupted", events[-1]
    run_id = events[-1]["run_id"]

    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        assert run is not None and run.status == "awaiting_review" and run.finished_at is None
    finally:
        db.close()
    assert checkpoint_rows(str(run_id))["checkpoints"] >= 1

    # 从对话入口审批：走 execute_workflow 的 resume 分支，到终态后清理
    resumed = client.post(f"/api/v1/workflows/{wid}/runs/{run_id}/resume",
                          headers=auth_headers, json={"decision": {"approved": True}})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "success"
    assert checkpoint_rows(str(run_id))["checkpoints"] == 0
