"""并行与汇聚节点（`12-差距补齐开发计划.md` 2.5，FR-029）：并发执行、汇聚输出、分支默认输入、图校验 400、分支失败语义。

并行超步内分支完成顺序不确定：steps 按多重集合比较，不比顺序。
"""
import time
import uuid

import pytest

from app.db.models import Run, RunNode, Workflow
from app.db.session import SessionLocal
from app.workflow.engine import build_workflow
from app.workflow.validation import branch_predecessors, validate_graph


def _node(node_id: str, node_type: str, **config) -> dict:
    return {"id": node_id, "type": node_type, "config": config}


def _edge(src: str, dst: str, when: str | None = None) -> dict:
    return {"from": src, "to": dst, **({"when": when} if when else {})}


def _code(node_id: str, code: str, **config) -> dict:
    return _node(node_id, "code", code=code, **config)


def _parallel_graph(branch_a: list[dict], branch_b: list[dict], tail: list[dict] | None = None) -> dict:
    """start → par → [branch_a…] / [branch_b…] → join → (tail…) → end。分支节点按列表顺序串联。"""
    tail = tail or []
    nodes = [_node("s", "start"), _node("par", "parallel"), *branch_a, *branch_b, _node("join", "join"), *tail, _node("e", "end")]
    edges = [_edge("s", "par")]
    for branch in (branch_a, branch_b):
        prev = "par"
        for n in branch:
            edges.append(_edge(prev, n["id"]))
            prev = n["id"]
        edges.append(_edge(prev, "join"))
    prev = "join"
    for n in tail:
        edges.append(_edge(prev, n["id"]))
        prev = n["id"]
    edges.append(_edge(prev, "e"))
    return {"nodes": nodes, "edges": edges}


def _invoke(graph: dict, input_value="x") -> dict:
    return build_workflow(graph).invoke({"input": input_value, "steps": []}, {"configurable": {"thread_id": "par-test-" + uuid.uuid4().hex[:12]}})


# ---------- 执行 ----------

def test_two_sleep_branches_run_concurrently_and_join_collects_tail_outputs():
    graph = _parallel_graph(
        [_code("a", "import time; time.sleep(1); result = 'A'")],
        [_code("b", "import time; time.sleep(1); result = 'B'")],
    )
    started = time.perf_counter()
    result = _invoke(graph, "in")
    elapsed = time.perf_counter() - started
    assert elapsed < 1.6, f"两条 1 秒分支串行了：{elapsed:.2f}s"
    assert result["output"] == {"a": "A", "b": "B"}
    assert sorted(result["steps"]) == ["code", "code", "join", "parallel"]
    assert result["node_outputs"] == {"par": "in", "a": "A", "b": "B", "join": {"a": "A", "b": "B"}}


def test_branch_nodes_default_input_is_own_predecessor():
    graph = _parallel_graph(
        [_code("a1", "result = 'a1:' + str(input)"), _code("a2", "result = 'a2:' + str(input)")],
        [_code("b", "result = 'b:' + str(input)")],
        tail=[_code("after", "result = sorted(input.keys())")],
    )
    assert branch_predecessors(graph) == {"a1": "par", "a2": "a1", "b": "par"}
    result = _invoke(graph, "x")
    outputs = result["node_outputs"]
    assert outputs["a1"] == "a1:x" and outputs["a2"] == "a2:a1:x" and outputs["b"] == "b:x"
    assert outputs["join"] == {"a2": "a2:a1:x", "b": "b:x"}
    assert outputs["after"] == ["a2", "b"]  # join 之后的节点默认输入是汇聚字典
    assert result["output"] == ["a2", "b"]


def test_branch_input_ref_to_input_and_node_path_still_work():
    graph = _parallel_graph(
        [_code("a", "result = {'n': 7}"), _code("a_next", "result = input * 2", input_ref="{{a.n}}")],
        [_code("b", "result = 'raw:' + str(input)", input_ref="{{input}}")],
    )
    result = _invoke(graph, "seed")
    assert result["node_outputs"]["a_next"] == 14 and result["node_outputs"]["b"] == "raw:seed"


def test_join_output_field_extracts_from_collected_dict():
    graph = _parallel_graph([_code("a", "result = {'v': 1}")], [_code("b", "result = {'v': 2}")])
    graph["nodes"][[n["id"] for n in graph["nodes"]].index("join")]["config"] = {"output_field": "b.v"}
    result = _invoke(graph)
    assert result["output"] == 2 and result["node_outputs"]["join"] == 2


# ---------- 校验 ----------

def _single_branch() -> dict:
    return {
        "nodes": [_node("s", "start"), _node("par", "parallel"), _code("a", "result = 1"), _node("join", "join"), _node("e", "end")],
        "edges": [_edge("s", "par"), _edge("par", "a"), _edge("a", "join"), _edge("join", "e")],
    }


def _loop_in_branch() -> dict:
    g = _parallel_graph([_node("lp", "loop", count=2)], [_code("b", "result = 2")])
    return g


def _different_joins() -> dict:
    g = _parallel_graph([_code("a", "result = 1")], [_code("b", "result = 2")])
    g["nodes"].append(_node("join2", "join"))
    g["edges"] = [e if not (e["from"] == "b" and e["to"] == "join") else _edge("b", "join2") for e in g["edges"]]
    g["edges"].append(_edge("join2", "e"))
    return g


def _output_ref_in_branch() -> dict:
    return _parallel_graph([_code("a", "result = 1", input_ref="{{output}}")], [_code("b", "result = 2")])


def _join_from_two_parallels() -> dict:
    g = _parallel_graph([_code("a", "result = 1")], [_code("b", "result = 2")])
    g["nodes"] += [_node("par2", "parallel"), _code("c", "result = 3"), _code("d", "result = 4")]
    g["edges"] += [_edge("s", "par2"), _edge("par2", "c"), _edge("par2", "d"), _edge("c", "join"), _edge("d", "join")]
    return g


INVALID = [
    (_single_branch, "并行节点 par 至少需要 2 条分支"),
    (_loop_in_branch, "并行分支内不支持 loop 节点（lp）"),
    (_different_joins, "并行节点 par 的分支必须汇聚到同一个汇聚节点"),
    (_output_ref_in_branch, "并行分支内的节点 a 不能引用 {{output}}"),
    (_join_from_two_parallels, "汇聚节点 join 的入边必须全部来自同一个并行节点且不少于 2 条"),
]


@pytest.mark.parametrize("build, fragment", INVALID, ids=["只有一条分支", "分支内含loop", "分支汇到不同join", "分支内引用output", "join入边来自不同parallel"])
def test_validate_graph_reports_rule(build, fragment):
    assert fragment in validate_graph(build())


@pytest.mark.parametrize("build, fragment", INVALID, ids=["只有一条分支", "分支内含loop", "分支汇到不同join", "分支内引用output", "join入边来自不同parallel"])
def test_saving_invalid_graph_returns_400(client, auth_headers, build, fragment):
    r = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-parallel-invalid", "description": "", "graph": build()})
    assert r.status_code == 400, r.text
    assert r.json()["detail"].startswith("图校验失败：") and fragment in r.json()["detail"]


def test_updating_to_invalid_graph_returns_400(client, auth_headers):
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-parallel-upd", "description": "", "graph": _parallel_graph([_code("a", "result = 1")], [_code("b", "result = 2")])})
    assert wf.status_code == 200, wf.text
    try:
        r = client.put(f"/api/v1/workflows/{wf.json()['id']}", headers=auth_headers, json={"name": "x", "description": "", "graph": _single_branch()})
        assert r.status_code == 400 and "至少需要 2 条分支" in r.json()["detail"]
    finally:
        client.delete(f"/api/v1/workflows/{wf.json()['id']}", headers=auth_headers)


def test_test_run_with_invalid_graph_returns_400(client, auth_headers):
    r = client.post("/api/v1/workflows/test-run", headers=auth_headers, json={"graph": _output_ref_in_branch(), "input": "x"})
    assert r.status_code == 400, r.text
    assert "不能引用 {{output}}" in r.json()["detail"]


def test_running_invalid_graph_returns_400_without_creating_run(client, auth_headers):
    """校验上线前保存的非法图（直接写库绕过校验）：运行返回 400，runs 表不新增记录。"""
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
    db = SessionLocal()
    try:
        w = Workflow(name="pytest-parallel-legacy", description="", graph=_single_branch(), created_by=me)
        db.add(w)
        db.commit()
        wid = w.id
    finally:
        db.close()
    try:
        r = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"input": "x"})
        assert r.status_code == 400, r.text
        assert "至少需要 2 条分支" in r.json()["detail"]
        db = SessionLocal()
        try:
            assert db.query(Run).filter(Run.workflow_id == wid).count() == 0
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_graph_without_parallel_is_unaffected_by_validation(client, auth_headers):
    graph = {
        "nodes": [
            _node("s", "start"), _node("cond", "condition", expression="input == 'go'"),
            _node("loop", "loop", count=2), _code("body", "result = 'ran'"), _code("other", "result = 'skipped'"), _node("e", "end"),
        ],
        "edges": [
            _edge("s", "cond"), _edge("cond", "loop", "true"), _edge("cond", "other", "false"),
            _edge("loop", "body", "loop"), _edge("loop", "e", "exit"), _edge("body", "loop"), _edge("other", "e"),
        ],
    }
    assert validate_graph(graph) == []
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-parallel-plain", "description": "", "graph": graph})
    assert wf.status_code == 200, wf.text
    try:
        r = client.post(f"/api/v1/workflows/{wf.json()['id']}/run", headers=auth_headers, json={"input": "go"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "success" and r.json()["steps"] == ["condition:True", "loop:1", "code", "loop:2"]
    finally:
        client.delete(f"/api/v1/workflows/{wf.json()['id']}", headers=auth_headers)


# ---------- 分支失败 ----------

def test_one_branch_failure_fails_run_while_other_branch_node_logs_success(client, auth_headers):
    graph = _parallel_graph(
        [_code("boom", "import time; time.sleep(0.5); raise ValueError('boom')")],
        [_code("fine", "import time; time.sleep(0.1); result = 'B'")],
    )
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-parallel-fail", "description": "", "graph": graph})
    assert wf.status_code == 200, wf.text
    try:
        r = client.post(f"/api/v1/workflows/{wf.json()['id']}/run", headers=auth_headers, json={"input": "x"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "failed" and "boom" in body["error"]
        db = SessionLocal()
        try:
            status_by_node = {n.node_id: n.status for n in db.query(RunNode).filter(RunNode.run_id == body["run_id"]).all()}
        finally:
            db.close()
        assert status_by_node["boom"] == "failed" and status_by_node["fine"] == "success"
        assert status_by_node["par"] == "success" and "join" not in status_by_node
    finally:
        client.delete(f"/api/v1/workflows/{wf.json()['id']}", headers=auth_headers)
