"""工作流引擎特征化测试（`12-差距补齐开发计划.md` 2.4a）：固化现有 10 类节点的 steps / node_outputs / output 行为，
作为 2.4 引擎状态改 reducer 与 2.5 并行节点的回归基线。

只用不依赖外部服务的节点（start / end / condition / code / loop / human_review），直接编译图执行，不落运行记录（run_id=None）。
断言到具体值：steps 逐字相同、node_outputs 逐键相同。
"""
import uuid

from langgraph.types import Command

from app.workflow.engine import build_workflow


def _node(node_id: str, node_type: str, **config) -> dict:
    return {"id": node_id, "type": node_type, "config": config}


def _edge(src: str, dst: str, when: str | None = None) -> dict:
    return {"from": src, "to": dst, **({"when": when} if when else {})}


def _run(graph: dict, input_value, resume=None) -> dict:
    """编译并执行；resume 非空时先跑到中断再用同一 thread_id 续跑。返回最终 state。"""
    g = build_workflow(graph)
    cfg = {"configurable": {"thread_id": "engine-test-" + uuid.uuid4().hex[:12]}}
    result = g.invoke({"input": input_value, "steps": []}, cfg)
    if resume is not None:
        assert "__interrupt__" in result, "预期先被人工审核节点中断"
        result = g.invoke(Command(resume=resume), cfg)
    return result


def _code(node_id: str, code: str, **config) -> dict:
    return _node(node_id, "code", code=code, **config)


# ---------- 条件节点 ----------

def _condition_graph() -> dict:
    return {
        "nodes": [
            _node("s", "start"), _node("cond", "condition", expression="input == 'yes'"),
            _code("code_a", "result = 'A'"), _code("code_b", "result = 'B'"), _node("e", "end"),
        ],
        "edges": [_edge("s", "cond"), _edge("cond", "code_a", "true"), _edge("cond", "code_b", "false"), _edge("code_a", "e"), _edge("code_b", "e")],
    }


def test_condition_true_branch():
    result = _run(_condition_graph(), "yes")
    assert result["steps"] == ["condition:True", "code"]
    assert result["node_outputs"] == {"code_a": "A"}
    assert result["output"] == "A" and result["condition_result"] is True


def test_condition_false_branch():
    result = _run(_condition_graph(), "no")
    assert result["steps"] == ["condition:False", "code"]
    assert result["node_outputs"] == {"code_b": "B"}
    assert result["output"] == "B" and result["condition_result"] is False


def test_condition_expression_error_takes_false_branch():
    graph = _condition_graph()
    graph["nodes"][1]["config"]["expression"] = "input.undefined_attr > 1"
    result = _run(graph, "yes")
    assert result["steps"] == ["condition:False", "code"] and result["node_outputs"] == {"code_b": "B"}


# ---------- 循环节点 ----------

def _loop_graph(**loop_config) -> dict:
    # loop 节点每经过一次 loop_index + 1；回环走 body 再回到 loop；退出到 end
    return {
        "nodes": [_node("s", "start"), _node("loop", "loop", **loop_config), _code("body", "result = 'ran'"), _node("e", "end")],
        "edges": [_edge("s", "loop"), _edge("loop", "body", "loop"), _edge("loop", "e", "exit"), _edge("body", "loop")],
    }


def test_loop_by_count_runs_loop_node_count_times_and_body_count_minus_one():
    # 现有语义：count=3 时 loop 节点经过 3 次（loop_index 1/2/3），第 3 次判 3 < 3 为假退出，body 只执行 2 次
    result = _run(_loop_graph(count=3), "x")
    assert result["steps"] == ["loop:1", "code", "loop:2", "code", "loop:3"]
    assert result["loop_index"] == 3
    assert result["node_outputs"] == {"body": "ran"} and result["output"] == "ran"


def test_loop_by_expression_exits_when_false():
    result = _run(_loop_graph(expression="loop_index < 2"), "x")
    assert result["steps"] == ["loop:1", "code", "loop:2"]
    assert result["loop_index"] == 2


# ---------- 人工审核 ----------

def test_human_review_interrupt_then_resume_runs_to_end():
    graph = {
        "nodes": [
            _node("s", "start"), _code("pre", "result = 'draft'"), _node("review", "human_review", instruction="请审核"),
            _code("post", "result = 'post:' + str(input)"), _node("e", "end"),
        ],
        "edges": [_edge("s", "pre"), _edge("pre", "review"), _edge("review", "post"), _edge("post", "e")],
    }
    g = build_workflow(graph)
    cfg = {"configurable": {"thread_id": "engine-test-" + uuid.uuid4().hex[:12]}}
    paused = g.invoke({"input": "x", "steps": []}, cfg)
    assert paused["steps"] == ["code"] and paused["node_outputs"] == {"pre": "draft"}
    assert paused["__interrupt__"][0].value == {"node_id": "review", "instruction": "请审核", "data": "draft"}

    result = g.invoke(Command(resume={"approved": True}), cfg)
    assert "__interrupt__" not in result
    assert result["steps"] == ["code", 'human_review:{"approved": true}', "code"]
    assert result["review_result"] == '{"approved": true}'
    assert result["node_outputs"] == {"pre": "draft", "review": {"approved": True}, "post": "post:{'approved': True}"}
    assert result["output"] == "post:{'approved': True}"


# ---------- 输入引用与输出提取 ----------

def _chain(second_code: str, **second_config) -> dict:
    return {
        "nodes": [_node("s", "start"), _code("code_a", "result = 'a:' + str(input)"), _code("code_b", second_code, **second_config), _node("e", "end")],
        "edges": [_edge("s", "code_a"), _edge("code_a", "code_b"), _edge("code_b", "e")],
    }


def test_first_node_defaults_to_input_and_next_defaults_to_previous_output():
    result = _run(_chain("result = 'b:' + str(input)"), "hello")
    assert result["node_outputs"] == {"code_a": "a:hello", "code_b": "b:a:hello"}
    assert result["output"] == "b:a:hello" and result["steps"] == ["code", "code"]


def test_input_ref_input():
    result = _run(_chain("result = 'b:' + str(input)", input_ref="{{input}}"), "hello")
    assert result["node_outputs"]["code_b"] == "b:hello"


def test_input_ref_output():
    result = _run(_chain("result = 'b:' + str(input)", input_ref="{{output}}"), "hello")
    assert result["node_outputs"]["code_b"] == "b:a:hello"


def test_input_ref_node_field_path():
    graph = _chain("result = 'b:' + str(input)", input_ref="{{code_a.user.name}}")
    graph["nodes"][1]["config"]["code"] = "result = {'user': {'name': 'lei'}}"
    result = _run(graph, "hello")
    assert result["node_outputs"] == {"code_a": {"user": {"name": "lei"}}, "code_b": "b:lei"}


def test_input_ref_missing_node_gives_none():
    result = _run(_chain("result = 'b:' + str(input)", input_ref="{{nope.x}}"), "hello")
    assert result["node_outputs"]["code_b"] == "b:None"


def test_output_field_dot_path_on_dict_and_json_string():
    graph = {
        "nodes": [
            _node("s", "start"),
            _code("code_a", "result = {'data': {'code': 200}}", output_field="data.code"),
            _code("code_b", "result = '{\"a\": {\"b\": [1, 2]}}'", output_field="a.b.1"),
            _node("e", "end"),
        ],
        "edges": [_edge("s", "code_a"), _edge("code_a", "code_b"), _edge("code_b", "e")],
    }
    result = _run(graph, "x")
    assert result["node_outputs"] == {"code_a": 200, "code_b": 2}
    assert result["output"] == 2


def test_node_outputs_accumulate_over_all_executed_nodes():
    graph = {
        "nodes": [_node("s", "start"), _code("c1", "result = 1"), _code("c2", "result = input + 1"), _code("c3", "result = input * 10"), _node("e", "end")],
        "edges": [_edge("s", "c1"), _edge("c1", "c2"), _edge("c2", "c3"), _edge("c3", "e")],
    }
    result = _run(graph, "ignored")
    assert result["steps"] == ["code", "code", "code"]
    assert result["node_outputs"] == {"c1": 1, "c2": 2, "c3": 20}
    assert result["output"] == 20 and result["input"] == "ignored"


def test_code_node_without_result_falls_back_to_output_variable():
    graph = {
        "nodes": [_node("s", "start"), _code("c1", "output = 'via-output'"), _node("e", "end")],
        "edges": [_edge("s", "c1"), _edge("c1", "e")],
    }
    result = _run(graph, "x")
    assert result["node_outputs"] == {"c1": "via-output"} and result["output"] == "via-output"
