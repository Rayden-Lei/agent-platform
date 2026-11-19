"""工作流输入输出契约（workflow/io_contract.py）的声明校验与转换边界。

与 test_workflow_io.py 的分工：那个文件走接口，验证"声明→保存→运行"的端到端链路；
这里直接对模块内的校验器下断言，专攻**库里存了坏声明**时的行为 ——
图是外部输入（可能由旧版本写入、也可能被脚本改过），解析失败必须明确报 400，
不能静默当成空声明（那会让一个声明了必填输入的工作流突然接受任意空入参）。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.exceptions import BizError
from app.workflow import io_contract
from app.workflow.io_contract import (
    MAX_VARIABLES,
    WorkflowOutput,
    WorkflowVariable,
    build_initial_state,
    convert_value,
    end_outputs,
    main_input,
    normalize_inputs,
    start_variables,
)


def _var(**kw) -> WorkflowVariable:
    return WorkflowVariable(**{"name": "x", "type": "text", **kw})


# --------------------------------------------------------------------------- 声明校验

def test_variable_name_must_be_identifier_like():
    """变量名要能写进 {{start.名字}}，所以与工具参数同一个正则。"""
    for bad in ("", "1abc", "a-b", "a b", "中文"):
        with pytest.raises(ValidationError):
            _var(name=bad)


def test_variable_name_is_stripped():
    assert _var(name="  ok_1  ").name == "ok_1"


def test_variable_rejects_unknown_type():
    with pytest.raises(ValidationError):
        _var(type="object")


def test_variable_rejects_extra_field():
    """extra=forbid：前端多传一个字段要报错，而不是被静默丢掉后使用者以为生效了。"""
    with pytest.raises(ValidationError):
        WorkflowVariable(name="x", type="text", nope=1)


def test_default_is_converted_to_declared_type():
    """"3" 这种默认值要按声明转成 3，否则运行时拿到的是字符串、比较结果全是错的。"""
    assert _var(type="integer", default="3").default == 3
    assert _var(type="number", default="1.5").default == 1.5
    assert _var(type="boolean", default="true").default is True


def test_bad_default_is_rejected_at_save_time():
    """默认值类型不符要在保存时拦住：等到运行才报，使用者已经离开编辑页了。"""
    with pytest.raises(ValidationError) as ei:
        _var(type="integer", default="abc")
    assert "默认值不合法" in str(ei.value)


def test_none_default_means_required():
    assert _var(default=None).default is None


def test_too_many_variables_rejected():
    with pytest.raises(ValidationError) as ei:
        io_contract.StartConfig(variables=[WorkflowVariable(name=f"v{i}") for i in range(MAX_VARIABLES + 1)])
    assert "最多" in str(ei.value)


def test_duplicate_variable_names_rejected():
    with pytest.raises(ValidationError) as ei:
        io_contract.StartConfig(variables=[WorkflowVariable(name="a"), WorkflowVariable(name="a")])
    assert "重名" in str(ei.value)


def test_output_name_validated():
    with pytest.raises(ValidationError):
        WorkflowOutput(name="1bad", ref="{{x}}")


def test_output_ref_required():
    with pytest.raises(ValidationError) as ei:
        WorkflowOutput(name="ok", ref="  ")
    assert "必须引用一个变量" in str(ei.value)


def test_duplicate_output_names_rejected():
    with pytest.raises(ValidationError) as ei:
        io_contract.EndConfig(outputs=[WorkflowOutput(name="a", ref="{{x}}"),
                                       WorkflowOutput(name="a", ref="{{y}}")])
    assert "重名" in str(ei.value)


def test_too_many_outputs_rejected():
    with pytest.raises(ValidationError):
        io_contract.EndConfig(outputs=[WorkflowOutput(name=f"o{i}", ref="{{x}}") for i in range(MAX_VARIABLES + 1)])


# --------------------------------------------------------------------------- 从图里取声明

def test_start_variables_merges_multiple_start_nodes():
    """多个开始节点按节点顺序合并（重名由保存时的图校验拦，这里不管）。"""
    graph = {"nodes": [
        {"type": "start", "config": {"variables": [{"name": "a"}]}},
        {"type": "llm", "config": {}},
        {"type": "start", "config": {"variables": [{"name": "b"}]}},
    ]}
    assert [v.name for v in start_variables(graph)] == ["a", "b"]


def test_start_variables_empty_when_no_start_node():
    assert start_variables({"nodes": [{"type": "llm"}]}) == []
    assert start_variables({}) == []
    assert start_variables(None) == []


def test_end_outputs_reads_end_node():
    graph = {"nodes": [{"type": "end", "config": {"outputs": [{"name": "answer", "ref": "{{n.data}}"}]}}]}
    assert [o.name for o in end_outputs(graph)] == ["answer"]


def test_bad_config_type_raises_400():
    """节点配置不是对象：图是外部输入，要明确报错而不是当空声明放过。"""
    with pytest.raises(BizError) as ei:
        start_variables({"nodes": [{"type": "start", "config": "oops"}]})
    assert ei.value.status_code == 400
    assert "必须是对象" in ei.value.detail


def test_bad_variables_type_raises_400():
    with pytest.raises(BizError) as ei:
        start_variables({"nodes": [{"type": "start", "config": {"variables": "oops"}}]})
    assert ei.value.status_code == 400
    assert "必须是数组" in ei.value.detail


def test_invalid_declaration_raises_400_with_field_hint():
    """库里存了坏声明：要报出是哪个字段不合法，否则排查只能靠猜。"""
    with pytest.raises(BizError) as ei:
        start_variables({"nodes": [{"type": "start", "config": {"variables": [{"name": "1bad"}]}}]})
    assert ei.value.status_code == 400
    assert "variables" in ei.value.detail


# --------------------------------------------------------------------------- 值转换

@pytest.mark.parametrize("value,var_type,expected", [
    (None, "text", (None, "")),
    ("true", "boolean", (True, "")),
    ("1", "boolean", (True, "")),
    ("是", "boolean", (True, "")),
    ("false", "boolean", (False, "")),
    ("0", "boolean", (False, "")),
    ("", "boolean", (False, "")),
    (True, "boolean", (True, "")),
    ("3", "integer", (3, "")),
    (" 3 ", "integer", (3, "")),
    ("1.5", "number", (1.5, "")),
    (5, "text", ("5", "")),
    ("x", "text", ("x", "")),
])
def test_convert_value(value, var_type, expected):
    assert convert_value(value, var_type) == expected


@pytest.mark.parametrize("value,var_type,fragment", [
    ("maybe", "boolean", "不是布尔值"),
    ("abc", "integer", "不是整数"),
    ("abc", "number", "不是数字"),
])
def test_convert_value_errors(value, var_type, fragment):
    got, err = convert_value(value, var_type)
    assert got is None and fragment in err


# --------------------------------------------------------------------------- 入参校验

def test_unknown_input_key_rejected():
    """未声明的键一律拒：否则使用者以为填了、实际没生效，排查起来毫无线索。"""
    with pytest.raises(BizError) as ei:
        normalize_inputs([_var(name="a")], {"a": "1", "b": "2"})
    assert "未声明的输入变量" in ei.value.detail
    assert "b" in ei.value.detail


def test_missing_required_reports_name():
    with pytest.raises(BizError) as ei:
        normalize_inputs([_var(name="required_one")], {})
    assert "缺少必填输入 required_one" in ei.value.detail


def test_blank_string_counts_as_missing():
    """全空白按"没填"处理：否则一个空格就能绕过必填校验。"""
    with pytest.raises(BizError) as ei:
        normalize_inputs([_var(name="a")], {"a": "   "})
    assert "缺少必填输入 a" in ei.value.detail


def test_default_used_when_missing():
    assert normalize_inputs([_var(name="a", default="d")], {}) == {"a": "d"}


def test_default_used_when_blank():
    assert normalize_inputs([_var(name="a", default="d")], {"a": ""}) == {"a": "d"}


def test_type_error_names_the_variable():
    with pytest.raises(BizError) as ei:
        normalize_inputs([_var(name="n", type="integer")], {"n": "abc"})
    assert "n:" in ei.value.detail and "不是整数" in ei.value.detail


def test_multiple_errors_are_all_reported():
    """一次把所有问题报出来：逐个修会让使用者来回提交好几轮。"""
    with pytest.raises(BizError) as ei:
        normalize_inputs([_var(name="a"), _var(name="n", type="integer")], {"n": "abc", "zzz": 1})
    assert "未声明的输入变量" in ei.value.detail
    assert "缺少必填输入 a" in ei.value.detail
    assert "不是整数" in ei.value.detail


def test_inputs_must_be_object():
    with pytest.raises(BizError) as ei:
        normalize_inputs([], ["a"])
    assert "必须是对象" in ei.value.detail


def test_no_variables_accepts_empty_inputs():
    assert normalize_inputs([], None) == {}
    assert normalize_inputs([], {}) == {}


# --------------------------------------------------------------------------- 主输入

def test_main_input_prefers_named_input():
    assert main_input({"input": "x", "other": "y"}) == "x"


def test_main_input_single_variable():
    assert main_input({"only": "v"}) == "v"


def test_main_input_returns_dict_when_ambiguous():
    """多个变量却没有一个叫 input：返回整个字典，节点用 {{start.变量名}} 取具体值。"""
    assert main_input({"a": 1, "b": 2}) == {"a": 1, "b": 2}


def test_main_input_empty_returns_empty_dict():
    assert main_input({}) == {}


# --------------------------------------------------------------------------- 初始 state

def test_build_initial_state_shape():
    graph = {"nodes": [{"type": "start", "config": {"variables": [{"name": "input"}]}}]}
    state = build_initial_state(graph, {"input": "hi"})
    assert state["input"] == "hi"
    assert state["vars"] == {"input": "hi"}
    # node_outputs.start 与 vars 是同一份：{{start.input}} 走通用引用路径
    assert state["node_outputs"]["start"] == {"input": "hi"}
    assert state["steps"] == []


def test_build_initial_state_validates():
    graph = {"nodes": [{"type": "start", "config": {"variables": [{"name": "req"}]}}]}
    with pytest.raises(BizError):
        build_initial_state(graph, {})
