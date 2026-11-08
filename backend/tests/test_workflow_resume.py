"""工作流续跑与运行列表的负向用例（docs/15 3.7.1）。

扫描时发现 `POST /workflows/{id}/runs/{run_id}/resume` 在整个测试集里只作为
一个 lambda 路径出现过一次，**没有任何直接断言**。而它是：

- 一个人工审核的**状态机入口**（只有 awaiting_review 能续）
- 一个**权限边界**：Key 只能续自己发起的运行，别人的 404 而不是 403
  （404 是为了不暴露"这条运行存在"）

这两件事写错都不会报错：前者会让任意状态被"续跑"，后者会让任何拿到 run_id 的 Key
替人审批。
"""
from __future__ import annotations

import uuid

import pytest

from app.db.models import Run, Workflow
from app.db.session import SessionLocal

START_END_GRAPH = {
    "nodes": [
        {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
        {"id": "e", "type": "end", "config": {}},
    ],
    "edges": [{"from": "s", "to": "e"}],
}


@pytest.fixture
def workflow(client, auth_headers):
    """建一个最小工作流，用完删掉（运行记录随 CASCADE 走）。"""
    r = client.post("/api/v1/workflows", headers=auth_headers, json={
        "name": "pytest-resume-wf-" + uuid.uuid4().hex[:6],
        "description": "续跑负向用例",
        "graph": START_END_GRAPH,
    })
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    try:
        yield wid
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def _make_run(workflow_id: int, status: str, api_key_id: int | None = None) -> int:
    """直接造一条指定状态的运行记录（不真跑图，测的是 resume 的状态门与归属门）。"""
    db = SessionLocal()
    try:
        owner = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        run = Run(
            run_type="workflow", workflow_id=workflow_id, user_id=owner.created_by,
            status=status, input={"question": "x"}, output={}, api_key_id=api_key_id,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def test_resume_requires_awaiting_review(client, auth_headers, workflow):
    """不是 awaiting_review 的运行不能续跑（400）—— 否则状态机可被任意跳转。"""
    for bad_status in ("running", "success", "failed", "cancelled"):
        rid = _make_run(workflow, bad_status)
        res = client.post(f"/api/v1/workflows/{workflow}/runs/{rid}/resume",
                          headers=auth_headers, json={"decision": {"approved": True}})
        assert res.status_code == 400, f"{bad_status}: {res.text}"
        assert "待审核" in res.text


def test_resume_missing_run_is_404(client, auth_headers, workflow):
    res = client.post(f"/api/v1/workflows/{workflow}/runs/99999999/resume",
                      headers=auth_headers, json={"decision": {"approved": True}})
    assert res.status_code == 404, res.text
    assert "运行记录不存在" in res.text


def test_resume_run_of_another_workflow_is_404(client, auth_headers, workflow):
    """运行不属于这个工作流 → 404（不是 400）：不暴露"这条运行属于别处"。"""
    other = client.post("/api/v1/workflows", headers=auth_headers, json={
        "name": "pytest-resume-other-" + uuid.uuid4().hex[:6], "description": "x", "graph": START_END_GRAPH,
    })
    other_id = other.json()["id"]
    try:
        rid = _make_run(other_id, "awaiting_review")
        res = client.post(f"/api/v1/workflows/{workflow}/runs/{rid}/resume",
                          headers=auth_headers, json={"decision": {"approved": True}})
        assert res.status_code == 404, res.text
    finally:
        client.delete(f"/api/v1/workflows/{other_id}", headers=auth_headers)


def test_resume_missing_workflow_is_404(client, auth_headers):
    res = client.post("/api/v1/workflows/99999999/runs/1/resume",
                      headers=auth_headers, json={"decision": {"approved": True}})
    assert res.status_code == 404, res.text


def test_caller_cannot_resume(client, caller_headers, auth_headers, workflow):
    """caller 不能续跑：审批是管理动作。"""
    rid = _make_run(workflow, "awaiting_review")
    res = client.post(f"/api/v1/workflows/{workflow}/runs/{rid}/resume",
                      headers=caller_headers, json={"decision": {"approved": True}})
    assert res.status_code == 403, res.text


def test_resume_decision_must_be_object(client, auth_headers, workflow):
    """decision 传非对象要 422（契约由 Pydantic 守），不能落成空审批。"""
    rid = _make_run(workflow, "awaiting_review")
    res = client.post(f"/api/v1/workflows/{workflow}/runs/{rid}/resume",
                      headers=auth_headers, json={"decision": "approved"})
    assert res.status_code == 422, res.text


# --------------------------------------------------------------------------- 运行列表

def test_list_workflow_runs_paginates(client, auth_headers, workflow):
    for _ in range(3):
        _make_run(workflow, "success")
    res = client.get(f"/api/v1/workflows/{workflow}/runs", headers=auth_headers, params={"page_size": 2})
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 3


def test_list_workflow_runs_filters_status(client, auth_headers, workflow):
    _make_run(workflow, "success")
    _make_run(workflow, "failed")
    res = client.get(f"/api/v1/workflows/{workflow}/runs", headers=auth_headers,
                     params={"status": "failed", "page_size": 50})
    assert res.status_code == 200, res.text
    assert all(i["status"] == "failed" for i in res.json()["items"])


def test_list_workflow_runs_rejects_bad_sort(client, auth_headers, workflow):
    """排序字段走白名单，不合法 400（防止被拼进 SQL）。"""
    res = client.get(f"/api/v1/workflows/{workflow}/runs", headers=auth_headers,
                     params={"sort": "evil;drop"})
    assert res.status_code == 400, res.text


def test_list_workflow_runs_of_missing_workflow_is_404(client, auth_headers):
    assert client.get("/api/v1/workflows/99999999/runs", headers=auth_headers).status_code == 404
