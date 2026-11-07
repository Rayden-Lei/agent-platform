"""工作流输入输出契约（docs/15 WF-04，2026-11-05）：开始节点声明输入变量、结束节点声明输出。

覆盖三件事：按声明校验并宽松转换入参、{{start.x}} 与主输入 input 的关系、定时任务与试运行也走同一套规则。
负向用例比正向重要：未声明的键、必填缺值、类型不符、声明本身写坏，都必须明确 400。
"""
import uuid

from app.workflow.io_contract import build_initial_state, main_input, normalize_inputs, start_variables


def _graph(variables=None, outputs=None, extra_node=None) -> dict:
    """start → (extra) → end 的最小图；variables / outputs 为空时不写声明（存量图的形状）。"""
    start_config = {} if variables is None else {"variables": variables}
    end_config = {} if outputs is None else {"outputs": outputs}
    nodes = [{"id": "s", "type": "start", "config": start_config}]
    if extra_node:
        nodes.append(extra_node)
    nodes.append({"id": "e", "type": "end", "config": end_config})
    edges = [{"from": "s", "to": "e"}]
    if extra_node:
        edges = [{"from": "s", "to": extra_node["id"]}, {"from": extra_node["id"], "to": "e"}]
    return {"nodes": nodes, "edges": edges}


DECLARED = [
    {"name": "question", "type": "text", "description": "用户问题"},
    {"name": "count", "type": "integer", "description": ""},
    {"name": "days", "type": "number", "description": "", "default": 7},
]


# ---------- 纯函数：声明与校验 ----------

def test_variables_parsed_from_start_node():
    names = [v.name for v in start_variables(_graph(DECLARED))]
    assert names == ["question", "count", "days"]


def test_empty_inputs_rejected_for_required_variables():
    """必填判定按「没有默认值」，两个必填都该报出来，且文案里带变量名。"""
    variables = start_variables(_graph(DECLARED))
    try:
        normalize_inputs(variables, {})
    except Exception as e:
        assert "缺少必填输入 question" in str(e) and "count" in str(e)
    else:
        raise AssertionError("必填缺值应当 400")


def test_unknown_key_rejected():
    """未声明的键必须拒绝：否则用户以为填了，实际没生效。"""
    try:
        normalize_inputs(start_variables(_graph(DECLARED)), {"question": "hi", "count": 1, "nope": "x"})
    except Exception as e:
        assert "未声明的输入变量" in str(e) and "nope" in str(e)
    else:
        raise AssertionError("未声明的键应当 400")


def test_loose_conversion_and_default():
    """表单传上来的都是字符串：按声明转换（"3" → 3），没填的用默认值。"""
    values = normalize_inputs(start_variables(_graph(DECLARED)), {"question": "hi", "count": "3"})
    assert values == {"question": "hi", "count": 3, "days": 7}


def test_type_mismatch_reports_variable():
    try:
        normalize_inputs(start_variables(_graph(DECLARED)), {"question": "hi", "count": "abc"})
    except Exception as e:
        assert "count" in str(e) and "不是整数" in str(e)
    else:
        raise AssertionError("类型不符应当 400")


def test_main_input_prefers_variable_named_input():
    """主输入规则：有 input 变量取它，只有单变量取它，否则整个字典。"""
    assert main_input({"input": "x", "other": "y"}) == "x"
    assert main_input({"only": "x"}) == "x"
    assert main_input({"a": "x", "b": "y"}) == {"a": "x", "b": "y"}
    assert main_input({}) == {}


def test_initial_state_exposes_vars_for_start_ref():
    state = build_initial_state(_graph(DECLARED), {"question": "hi", "count": 2})
    assert state["vars"] == {"question": "hi", "count": 2, "days": 7}
    assert state["node_outputs"]["start"] == state["vars"]
    # 没有叫 input 的变量且有多个变量 → 主输入是整个字典
    assert state["input"] == state["vars"]


# ---------- 接口：保存校验、运行、试运行、声明查询 ----------

def test_save_rejects_bad_declaration(client, auth_headers):
    """声明本身写坏要在保存时 400：重名、名字不合法、超量。"""
    dup = _graph([{"name": "a", "type": "text"}, {"name": "a", "type": "text"}])
    r = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-io-dup", "description": "", "graph": dup})
    assert r.status_code == 400 and "重名" in r.json()["detail"]
    bad_name = _graph([{"name": "1bad", "type": "text"}])
    r = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-io-name", "description": "", "graph": bad_name})
    assert r.status_code == 400 and "不合法" in r.json()["detail"]


def test_run_uses_declared_inputs_and_reports_missing(client, auth_headers):
    """运行按声明校验：缺必填 400 且不建运行记录；填对了变量能进 {{start.question}}。"""
    graph = _graph(DECLARED)
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-io-" + uuid.uuid4().hex[:4], "description": "", "graph": graph})
    assert wf.status_code == 200, wf.text
    wid = wf.json()["id"]
    try:
        missing = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"inputs": {"question": "hi"}})
        assert missing.status_code == 400 and "缺少必填输入" in missing.json()["detail"]
        ok = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"inputs": {"question": "hi", "count": "3"}})
        assert ok.status_code == 200 and ok.json()["status"] == "success", ok.text
    finally:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


def test_parameters_endpoint_lists_declarations(client, auth_headers):
    """运行弹窗与外部调用方靠这个接口知道要填什么；必填由「没有默认值」推出。"""
    graph = _graph(DECLARED, outputs=[{"name": "answer", "ref": "{{s}}"}])
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-io-params-" + uuid.uuid4().hex[:4], "description": "", "graph": graph}).json()
    try:
        r = client.get(f"/api/v1/workflows/{wf['id']}/parameters", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [v["name"] for v in body["variables"]] == ["question", "count", "days"]
        required = {v["name"]: v["required"] for v in body["variables"]}
        assert required == {"question": True, "count": True, "days": False}
        assert body["outputs"] == [{"name": "answer", "ref": "{{s}}"}]
    finally:
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)


def test_test_run_also_validates_inputs(client, auth_headers):
    """试运行与正式运行同一套校验：测试通过就意味着正式运行也能跑通。"""
    graph = _graph(DECLARED)
    bad = client.post("/api/v1/workflows/test-run", headers=auth_headers, json={"graph": graph, "inputs": {"nope": 1}})
    assert bad.status_code == 400 and "未声明的输入变量" in bad.json()["detail"]
    ok = client.post("/api/v1/workflows/test-run", headers=auth_headers, json={"graph": graph, "inputs": {"question": "hi", "count": 1}})
    assert ok.status_code == 200 and ok.json()["status"] == "success", ok.text


def test_end_outputs_declared_shape(client, auth_headers):
    """结束节点声明输出后，响应里的 output 变成 {输出名: 值}；没声明时保持上游输出。"""
    code = {"id": "c", "type": "code", "config": {"code": "result = 'v'"}}
    declared = _graph([{"name": "input", "type": "text"}], outputs=[{"name": "answer", "ref": "{{c}}"}], extra_node=code)
    r = client.post("/api/v1/workflows/test-run", headers=auth_headers, json={"graph": declared, "inputs": {"input": "x"}})
    assert r.status_code == 200, r.text
    assert r.json()["output"] == {"answer": "v"}
    plain = _graph([{"name": "input", "type": "text"}], extra_node=code)
    r2 = client.post("/api/v1/workflows/test-run", headers=auth_headers, json={"graph": plain, "inputs": {"input": "x"}})
    assert r2.json()["output"] == "v"


def _ensure_calculator_tool(client, auth_headers) -> int:
    """确保库里有一行 calculator 工具，返回它的 id（已存在则复用）。

    为什么需要它：calculator / current_time 是**代码内置**的能力（每个智能体无条件挂上），
    但工作流工具节点是按 `tools` 表里的名字查的（engine._make_tool_node）。空库时那一行不存在，
    节点直接返回「工具不存在」。本地开发库早就被建过了，所以这两个用例只在 CI 的空库上失败。

    造的这行带 pytest- 前缀，会话结束由 tests/cleanup.py 回收。
    """
    existing = client.get("/api/v1/tools", headers=auth_headers, params={"page_size": 100}).json()["items"]
    found = next((t for t in existing if t["name"] == "calculator"), None)
    if found is not None:
        return found["id"]
    created = client.post("/api/v1/tools", headers=auth_headers, json={
        "name": "calculator", "description": "计算数学表达式", "type": "builtin", "config": {}, "timeout": 30,
    })
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_tool_node_resolves_ref_in_fixed_args(client, auth_headers):
    """工具节点的固定参数写 {{start.x}} 时按引用取值（WF-27），不拼字符串。"""
    _ensure_calculator_tool(client, auth_headers)
    graph = {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "expression", "type": "text"}]}},
            {"id": "t", "type": "tool", "config": {"tool_name": "calculator", "args": {"expression": "{{start.expression}}"}}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "t"}, {"from": "t", "to": "e"}],
    }
    r = client.post("/api/v1/workflows/test-run", headers=auth_headers, json={"graph": graph, "inputs": {"expression": "2+3*4"}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "success", r.text
    assert "14" in str(r.json()["output"])


def test_builtin_tool_exposes_parameter_declaration(client, auth_headers):
    """内置工具的声明随 config 下发（WF-26），前端据此生成表单而不是让人手写 JSON。"""
    _ensure_calculator_tool(client, auth_headers)
    tools = client.get("/api/v1/tools", headers=auth_headers, params={"page_size": 100}).json()["items"]
    calc = next(t for t in tools if t["name"] == "calculator")
    properties = calc["config"]["parameters"]["properties"]
    assert list(properties) == ["expression"] and calc["config"]["parameters"]["required"] == ["expression"]
