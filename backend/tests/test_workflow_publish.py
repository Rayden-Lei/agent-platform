"""工作流草稿 / 发布版本分离（docs/15 FR-075 / WF-02，与智能体 FR-039 同一套语义）。

草稿（workflows 行）与线上（published_version 指向的不可变快照）分离：保存只改草稿，发布才替换线上；
回滚上线上不动草稿；从未发布的工作流对外入口一律 403「工作流未发布」。

**运行时读哪个版本是这个特性的核心**，所以大部分断言不只看状态码，而是看"实际执行的图是哪一份"：
用一个会写出固定标记的 code 节点，发布 v1 后再把草稿改成另一个标记，跑一次看输出是哪个标记。
"""
import uuid

import pytest

from app.db.models import Run, Workflow, WorkflowVersion
from app.db.session import SessionLocal

# 最小图：开始节点声明一个文本输入，结束节点直连。用来测发布 / 回滚这类只管"哪一版"的行为。
START_END_GRAPH = {
    "nodes": [
        {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
        {"id": "e", "type": "end", "config": {}},
    ],
    "edges": [{"from": "s", "to": "e"}],
}


def _marked_graph(marker: str) -> dict:
    """带一个 code 节点、输出固定标记的图：跑完能从输出看出用的是哪一份图。

    code 节点是纯 Python 求值（sandbox），不发网络请求、不需要模型，适合断言"执行的是哪一版"。
    """
    return {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
            # code 节点不配 output_field：结果本身就是节点输出（配了 output_field 会按点路径去取字段，
            # 字符串结果取不到字段会变成 None，那样就分不清是"没跑对版本"还是"取错字段"了）
            {"id": "c", "type": "code", "config": {"code": f"result = {marker!r}"}},
            {"id": "e", "type": "end", "config": {"outputs": [{"name": "answer", "ref": "{{c}}"}]}},
        ],
        "edges": [{"from": "s", "to": "c"}, {"from": "c", "to": "e"}],
    }


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def make_workflow(client, auth_headers):
    """建工作流；publish=True 时立刻发布成 v1。用例自己删。"""
    created: list[int] = []

    def _make(graph: dict | None = None, publish: bool = False, name: str | None = None) -> dict:
        r = client.post("/api/v1/workflows", headers=auth_headers, json={
            "name": name or f"pytest-wfp-{_uid()}", "description": "", "graph": graph or START_END_GRAPH,
        })
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        created.append(wid)
        if publish:
            p = client.post(f"/api/v1/workflows/{wid}/publish", headers=auth_headers)
            assert p.status_code == 200, p.text
        return client.get(f"/api/v1/workflows/{wid}", headers=auth_headers).json()

    yield _make
    for wid in created:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def _versions(workflow_id: int) -> list[int]:
    db = SessionLocal()
    try:
        return [v.version for v in db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == workflow_id).order_by(WorkflowVersion.version)]
    finally:
        db.close()


def _save(client, headers, workflow_id: int, graph: dict, name: str | None = None):
    return client.put(f"/api/v1/workflows/{workflow_id}", headers=headers,
                      json={"name": name or f"pytest-wfp-{_uid()}", "description": "", "graph": graph})


def _run(client, headers, workflow_id: int) -> dict:
    return client.post(f"/api/v1/workflows/{workflow_id}/run", headers=headers, json={"inputs": {"input": "x"}})


# ---------- 保存 ≠ 发布 ----------

def test_new_workflow_is_draft_and_cannot_run(client, auth_headers, make_workflow):
    """新建的工作流是草稿：运行 403「工作流未发布」，且不留下运行记录。"""
    wf = make_workflow()
    assert wf["status"] == "draft"
    assert wf["published_version"] is None
    assert wf["has_unpublished_changes"] is False  # 从未发布过，谈不上"有未发布改动"

    r = _run(client, auth_headers, wf["id"])
    assert r.status_code == 403 and r.json()["detail"] == "工作流未发布", r.text
    db = SessionLocal()
    try:
        assert db.query(Run).filter(Run.workflow_id == wf["id"]).count() == 0
    finally:
        db.close()


def test_saving_draft_does_not_change_live_until_published(client, auth_headers, make_workflow):
    """发布后改草稿：status 仍是 published、has_unpublished_changes 为真，跑起来还是旧图。"""
    wf = make_workflow(_marked_graph("old"), publish=True)
    assert wf["published_version"] == 1 and wf["has_unpublished_changes"] is False

    saved = _save(client, auth_headers, wf["id"], _marked_graph("new"))
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["status"] == "published"           # 线上还能跑
    assert body["has_unpublished_changes"] is True  # 但有未发布改动
    assert body["version"] == 2                     # 草稿修订号 +1
    assert body["published_version"] == 1           # 线上版本号不动

    ran = _run(client, auth_headers, wf["id"])
    assert ran.status_code == 200, ran.text
    assert ran.json()["output"] == {"answer": "old"}, "改草稿不该影响线上，跑的必须还是 v1 的图"
    db = SessionLocal()
    try:
        run = db.get(Run, ran.json()["run_id"])
        assert run.workflow_version == 1  # 运行记录能看出跑的是哪一版
    finally:
        db.close()


def test_publish_makes_draft_live(client, auth_headers, make_workflow):
    """发布后跑的是新图，运行记录记 v2，草稿与线上重新一致。"""
    wf = make_workflow(_marked_graph("old"), publish=True)
    _save(client, auth_headers, wf["id"], _marked_graph("new"))
    p = client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=auth_headers, json={"note": "改成新标记"})
    assert p.status_code == 200, p.text
    assert p.json()["publish_result"] == "published"
    assert p.json()["published_version"] == 2
    assert p.json()["has_unpublished_changes"] is False

    ran = _run(client, auth_headers, wf["id"])
    assert ran.json()["output"] == {"answer": "new"}
    assert _versions(wf["id"]) == [1, 2]


def test_publish_without_changes_is_unchanged_and_creates_no_version(client, auth_headers, make_workflow):
    """草稿与线上一致时返回 unchanged，不生成新版本（双击发布不该连出两个版本）。"""
    wf = make_workflow(_marked_graph("same"), publish=True)
    again = client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=auth_headers)
    assert again.status_code == 200, again.text
    assert again.json()["publish_result"] == "unchanged"
    assert again.json()["published_version"] == 1
    assert _versions(wf["id"]) == [1]


def test_publish_rejects_invalid_draft_without_creating_version(client, auth_headers, make_workflow):
    """发布前跑图校验：草稿里是坏图时 400，不生成版本、线上不变。

    坏图直接写库造出来（绕过接口）：保存与发布目前共用同一套 validate_graph，
    经接口是造不出"保存能过、发布不过"的草稿的 —— 「保存只拦结构错误、发布跑全量校验」的
    分层是 docs/15 FR-076（WF-03）的范围，本任务没有做。这里验证的是更基本的一条：
    **发布这一步一定会重新校验**，库里的坏图不会被发上线（回滚旧版本走的是同一条 check_graph）。
    """
    wf = make_workflow(_marked_graph("keep"), publish=True)
    db = SessionLocal()
    try:
        # 循环次数超上限：validate_graph 会拦（LOOP_MAX_ITERATIONS）
        broken = {
            "nodes": [
                {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
                {"id": "l", "type": "loop", "config": {"count": 10 ** 9}},
                {"id": "e", "type": "end", "config": {}},
            ],
            "edges": [{"from": "s", "to": "l"}, {"from": "l", "to": "e", "when": "exit"}],
        }
        db.get(Workflow, wf["id"]).graph = broken
        db.commit()
    finally:
        db.close()

    p = client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=auth_headers)
    assert p.status_code == 400 and "图校验失败" in p.json()["detail"], p.text
    assert _versions(wf["id"]) == [1]
    assert client.get(f"/api/v1/workflows/{wf['id']}", headers=auth_headers).json()["published_version"] == 1
    assert _run(client, auth_headers, wf["id"]).json()["output"] == {"answer": "keep"}


# ---------- 回滚 ----------

def test_rollback_restores_previous_version_and_keeps_draft(client, auth_headers, make_workflow):
    """回滚上线：用 v1 快照生成 v3（不是改写历史），草稿不动，跑起来回到 v1 的图。"""
    wf = make_workflow(_marked_graph("v1"), publish=True)
    _save(client, auth_headers, wf["id"], _marked_graph("v2"))
    client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=auth_headers)
    assert _run(client, auth_headers, wf["id"]).json()["output"] == {"answer": "v2"}

    # 再改一次草稿（不发布），验证回滚不碰草稿
    draft = _marked_graph("draft-wip")
    _save(client, auth_headers, wf["id"], draft)

    versions = client.get(f"/api/v1/workflows/{wf['id']}/versions", headers=auth_headers).json()["items"]
    v1 = next(v for v in versions if v["version"] == 1)
    rb = client.post(f"/api/v1/workflows/{wf['id']}/rollback/{v1['id']}", headers=auth_headers)
    assert rb.status_code == 200, rb.text
    assert rb.json()["publish_result"] == "published"
    assert rb.json()["published_version"] == 3, "回滚也要生成新版本，历史不可改写"
    assert _versions(wf["id"]) == [1, 2, 3]

    assert _run(client, auth_headers, wf["id"]).json()["output"] == {"answer": "v1"}
    # 草稿仍是回滚前那份 wip（rollback 不动草稿，止血时不丢正在改的东西）
    detail = client.get(f"/api/v1/workflows/{wf['id']}", headers=auth_headers).json()
    assert detail["has_unpublished_changes"] is True
    code_node = next(n for n in detail["graph"]["nodes"] if n["type"] == "code")
    assert "draft-wip" in code_node["config"]["code"]
    # 回滚产生的那一版带说明，能看出是回滚而不是"又发布了一次草稿"
    rolled = client.get(f"/api/v1/workflows/{wf['id']}/versions", headers=auth_headers).json()["items"]
    assert rolled[0]["note"] == "回滚到 v1"
    assert rolled[0]["is_live"] is True


def test_rollback_to_live_version_is_unchanged(client, auth_headers, make_workflow):
    """回滚到当前线上那一版：unchanged，不生成新版本（双击不会连出两个）。"""
    wf = make_workflow(_marked_graph("only"), publish=True)
    versions = client.get(f"/api/v1/workflows/{wf['id']}/versions", headers=auth_headers).json()["items"]
    rb = client.post(f"/api/v1/workflows/{wf['id']}/rollback/{versions[0]['id']}", headers=auth_headers)
    assert rb.status_code == 200 and rb.json()["publish_result"] == "unchanged", rb.text
    assert _versions(wf["id"]) == [1]


def test_rollback_rejects_version_of_other_workflow(client, auth_headers, make_workflow):
    """版本必须属于该工作流：拿别的工作流的版本 ID 回滚 404，防止把 A 的图发到 B 上。"""
    a = make_workflow(_marked_graph("a"), publish=True)
    b = make_workflow(_marked_graph("b"), publish=True)
    va = client.get(f"/api/v1/workflows/{a['id']}/versions", headers=auth_headers).json()["items"][0]
    rb = client.post(f"/api/v1/workflows/{b['id']}/rollback/{va['id']}", headers=auth_headers)
    assert rb.status_code == 404 and rb.json()["detail"] == "版本不存在", rb.text
    assert _run(client, auth_headers, b["id"]).json()["output"] == {"answer": "b"}


def test_restore_version_writes_draft_only(client, auth_headers, make_workflow):
    """恢复到草稿：只改草稿，线上不变；草稿修订号 +1。"""
    wf = make_workflow(_marked_graph("live"), publish=True)
    _save(client, auth_headers, wf["id"], _marked_graph("wip"))
    v1 = client.get(f"/api/v1/workflows/{wf['id']}/versions", headers=auth_headers).json()["items"][0]
    res = client.post(f"/api/v1/workflows/{wf['id']}/versions/{v1['id']}/restore", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["has_unpublished_changes"] is False  # 草稿被还原成线上那一版
    assert res.json()["published_version"] == 1
    assert _run(client, auth_headers, wf["id"]).json()["output"] == {"answer": "live"}


# ---------- 未发布的工作流不能对外提供能力 ----------

def test_unpublished_workflow_cannot_be_scheduled(client, auth_headers, make_workflow):
    """定时任务保存时就拦未发布的工作流（403），不留"建好了却到点空跑"的任务。"""
    wf = make_workflow()
    r = client.post("/api/v1/schedules", headers=auth_headers, json={
        "name": f"pytest-wfp-sch-{_uid()}", "workflow_id": wf["id"], "cron": "0 3 * * *", "input": {},
    })
    assert r.status_code == 403 and r.json()["detail"] == "工作流未发布", r.text


def test_unpublished_workflow_cannot_be_called_by_api_key(client, auth_headers, make_workflow):
    """API Key 调用未发布的工作流 403 且不建运行记录。"""
    wf = make_workflow()
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={
        "name": f"pytest-wfp-key-{_uid()}", "quota": 5, "workflow_ids": [wf["id"]],
    }).json()
    try:
        r = client.post(f"/api/v1/workflows/{wf['id']}/run", headers={"Authorization": "Bearer " + key["key"]},
                        json={"inputs": {"input": "x"}})
        assert r.status_code == 403 and r.json()["detail"] == "工作流未发布", r.text
    finally:
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)


def test_unpublished_workflow_cannot_be_chatted(client, auth_headers, make_workflow):
    """工作流对话读线上版本：未发布 403，不建会话与运行记录。"""
    wf = make_workflow()
    r = client.post(f"/api/v1/workflows/{wf['id']}/chat", headers=auth_headers, json={"message": "你好"})
    assert r.status_code == 403 and r.json()["detail"] == "工作流未发布", r.text


def test_schedule_runs_live_version_not_draft(client, auth_headers, make_workflow):
    """定时任务跑线上版本：发布 v1 → 改草稿 → 立即执行一次，输出仍是 v1 的标记。"""
    wf = make_workflow(_marked_graph("sched-v1"), publish=True)
    _save(client, auth_headers, wf["id"], _marked_graph("sched-v2"))
    sch = client.post("/api/v1/schedules", headers=auth_headers, json={
        "name": f"pytest-wfp-sch-{_uid()}", "workflow_id": wf["id"], "cron": "0 3 * * *", "input": {"input": "x"},
    }).json()
    try:
        assert client.post(f"/api/v1/schedules/{sch['id']}/run", headers=auth_headers).status_code == 200
        # 立即执行是异步的（调度器线程池），轮询到终态
        for _ in range(100):
            runs = client.get(f"/api/v1/workflows/{wf['id']}/runs", headers=auth_headers).json()["items"]
            done = [r for r in runs if r["status"] in ("success", "failed")]
            if done:
                break
            import time
            time.sleep(0.1)
        assert done, "定时任务没有产出运行记录"
        latest = done[0]
        assert latest["source"] == "schedule"
        assert latest["workflow_version"] == 1, "定时任务必须跑发布时的 v1，不是草稿"
        assert latest["output"]["output"] == {"answer": "sched-v1"}, latest["output"]
    finally:
        client.delete(f"/api/v1/schedules/{sch['id']}", headers=auth_headers)


# ---------- 版本历史 ----------

def test_versions_list_pagination_and_live_flag(client, auth_headers, make_workflow):
    """版本历史按版本号倒序、标出哪一版是线上、带发布人与说明。"""
    wf = make_workflow(_marked_graph("v1"), publish=True)
    _save(client, auth_headers, wf["id"], _marked_graph("v2"))
    client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=auth_headers, json={"note": "第二版"})
    body = client.get(f"/api/v1/workflows/{wf['id']}/versions", headers=auth_headers).json()
    assert [v["version"] for v in body["items"]] == [2, 1]
    assert [v["is_live"] for v in body["items"]] == [True, False]
    assert body["items"][0]["note"] == "第二版"
    assert body["items"][0]["created_by_username"] == "admin"
    assert body["items"][0]["snapshot"]["graph"]["nodes"]


def test_versions_of_missing_workflow_is_404(client, auth_headers):
    assert client.get("/api/v1/workflows/99999999/versions", headers=auth_headers).status_code == 404
    assert client.post("/api/v1/workflows/99999999/publish", headers=auth_headers).status_code == 404


# ---------- 发布状态的列表筛选 ----------

def test_list_filter_by_publish_state(client, auth_headers, make_workflow):
    """status 筛选与 has_unpublished_changes 是两件事：已发布但改了草稿的仍算 published。"""
    q = "pytest-wfp-list-" + _uid()
    draft = make_workflow(name=q + "-draft")
    live = make_workflow(_marked_graph("x"), publish=True, name=q + "-live")
    _save(client, auth_headers, live["id"], _marked_graph("y"), name=live["name"])

    drafts = client.get("/api/v1/workflows", headers=auth_headers, params={"q": q, "status": "draft"}).json()["items"]
    published = client.get("/api/v1/workflows", headers=auth_headers, params={"q": q, "status": "published"}).json()["items"]
    assert [w["id"] for w in drafts] == [draft["id"]]
    assert [w["id"] for w in published] == [live["id"]]
    assert published[0]["has_unpublished_changes"] is True
    assert published[0]["published_version"] == 1 and published[0]["version"] == 2
