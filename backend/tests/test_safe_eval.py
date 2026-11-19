"""工作流表达式求值器（workflow/safe_eval.py）的安全边界与求值分支。

为什么单独测：这是**替代 eval 的白名单求值器**。改造前条件节点用
eval(expr, {"__builtins__": {}}, ns)，从空元组就能走到 Popen 执行任意命令（2026-11-14 审计）。
这里每一条拒绝断言都是一道门：漏一条就是远程代码执行。

现有 test_outbound_security.py 覆盖了"能不能逃逸"的主干，本文件补：
白名单内每个合法形态都真的能算（否则改造后正常流程反而坏了）、
以及各类语法节点的拒绝理由要准确（报错要能指导使用者改表达式）。
"""
from __future__ import annotations

import pytest

from app.workflow import safe_eval
from app.workflow.safe_eval import ConditionSyntaxError, evaluate, validate_expression


# --------------------------------------------------------------------------- 逃逸必须被拒

@pytest.mark.parametrize("expr", [
    "().__class__.__base__.__subclasses__()",
    "(1).__class__.__mro__",
    "open('/etc/passwd')",
    "__import__('os').system('id')",
    "eval('1+1')",
    "exec('x=1')",
    "getattr(x, 'y')",
    "[x for x in range(10)]",
    "{'a': 1}",
    "{1, 2}",
    "lambda: 1",
    "x if y else z",
    "f'{x}'",
    "(x := 1)",
    "await x",
    "yield 1",
    "x[1:2]",
])
def test_escape_attempts_are_rejected(expr):
    """这些是"从表达式走到对象图"的已知入口，任何一个能过就等于 RCE。"""
    with pytest.raises(ConditionSyntaxError):
        validate_expression(expr)


def test_attribute_access_is_rejected_even_on_a_name():
    """a.b 本身不执行代码，但它是对象图的入口（a 可以是任意对象）。
    白名单里没有 Attribute，所以哪怕看起来无害也要拒。"""
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression("user.name")
    assert "不支持的语法" in str(ei.value)


def test_power_operator_is_rejected():
    """** 不算术白名单里：9**9**9 会持有 GIL 把后端卡死（docs/15 RS-16 的同类事故）。"""
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression("9 ** 9 ** 9")
    assert "不支持的运算符" in str(ei.value)


def test_floor_division_is_rejected():
    """// 与 % 里只放行了 %：条件表达式用不到整除，少放一种就少一个口子。"""
    with pytest.raises(ConditionSyntaxError):
        validate_expression("7 // 2")


def test_unknown_function_is_rejected():
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression("danger(1)")
    assert "不支持的函数" in str(ei.value)


def test_star_args_rejected():
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression("max(*x)")
    assert "*args" in str(ei.value)


def test_kwargs_spread_rejected():
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression("max(**x)")
    assert "**kwargs" in str(ei.value)


def test_non_string_expression_rejected():
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression(123)
    assert "必须是字符串" in str(ei.value)


def test_empty_expression_rejected():
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression("   ")
    assert "表达式为空" in str(ei.value)


def test_oversize_expression_rejected():
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression("1 + " * 1000 + "1")
    assert "表达式过长" in str(ei.value)


def test_syntax_error_is_translated():
    with pytest.raises(ConditionSyntaxError) as ei:
        validate_expression("1 +")
    assert "语法错误" in str(ei.value)


# --------------------------------------------------------------------------- 合法形态必须能算

@pytest.mark.parametrize("expr,env,expected", [
    ("1 + 2", {}, 3),
    ("10 - 3", {}, 7),
    ("4 * 5", {}, 20),
    ("7 / 2", {}, 3.5),
    ("7 % 3", {}, 1),
    ("-5", {}, -5),
    ("+5", {}, 5),
    ("not True", {}, False),
    ("x > 3", {"x": 5}, True),
    ("x == 'a'", {"x": "a"}, True),
    ("x != 1", {"x": 2}, True),
    ("x < 1", {"x": 0}, True),
    ("x <= 1", {"x": 1}, True),
    ("x >= 1", {"x": 2}, True),
    ("x in [1, 2]", {"x": 2}, True),
    ("x not in [1, 2]", {"x": 3}, True),
    ("x is None", {"x": None}, True),
    ("x is not None", {"x": 1}, True),
    ("len(s) > 2", {"s": "abc"}, True),
    ("int(v) == 3", {"v": "3"}, True),
    ("float(v) > 1", {"v": "1.5"}, True),
    ("bool(v)", {"v": 1}, True),
    ("abs(v) == 3", {"v": -3}, True),
    ("min(a, b) == 1", {"a": 1, "b": 2}, True),
    ("max(a, b) == 2", {"a": 1, "b": 2}, True),
    ("sum([1, 2, 3]) == 6", {}, True),
    ("round(1.6) == 2", {}, True),
    ("str(v) == '5'", {"v": 5}, True),
    ("d['k'] == 1", {"d": {"k": 1}}, True),
    ("arr[0] == 1", {"arr": [1, 2]}, True),
    ("(1, 2)[0] == 1", {}, True),
])
def test_legal_expressions_evaluate(expr, env, expected):
    """白名单里的每个形态都要真的算得出来 —— 只测拒绝会让"改造完正常流程跑不动"漏过去。"""
    assert evaluate(expr, env) is expected if isinstance(expected, bool) else evaluate(expr, env) == expected


def test_and_or_short_circuit():
    """短路求值：and 遇假就停、or 遇真就停，否则未定义的变量会被误报成错误。"""
    assert evaluate("a and b", {"a": False}) is False
    assert evaluate("a or b", {"a": True}) is True
    assert evaluate("a and b", {"a": True, "b": 1}) == 1


def test_chained_comparison():
    assert evaluate("1 < 2 < 3", {}) is True
    assert evaluate("1 < 3 < 2", {}) is False


# --------------------------------------------------------------------------- 求值期错误收口

def test_unknown_variable_is_reported():
    """引用了没传进来的变量：报变量名，让使用者知道是调用方没给值。"""
    with pytest.raises(ConditionSyntaxError) as ei:
        evaluate("nope > 1", {})
    assert "未知变量：nope" in str(ei.value)


def test_division_by_zero_is_reported():
    """x/0 是笔误，不该让整个运行抛 ZeroDivisionError 崩掉。"""
    with pytest.raises(ConditionSyntaxError) as ei:
        evaluate("x / 0", {"x": 1})
    assert "除以 0" in str(ei.value)


def test_modulo_by_zero_is_reported():
    with pytest.raises(ConditionSyntaxError) as ei:
        evaluate("x % 0", {"x": 1})
    assert "除以 0" in str(ei.value)


def test_type_error_is_wrapped():
    """"abc" > 1 属于表达式写错：统一收口成 ConditionSyntaxError，调用方按 false 处理并记 WARN。"""
    with pytest.raises(ConditionSyntaxError) as ei:
        evaluate("s > 1", {"s": "abc"})
    assert "求值失败" in str(ei.value)


def test_missing_key_is_wrapped():
    with pytest.raises(ConditionSyntaxError) as ei:
        evaluate("d['nope'] == 1", {"d": {}})
    assert "求值失败" in str(ei.value)


def test_index_error_is_wrapped():
    with pytest.raises(ConditionSyntaxError) as ei:
        evaluate("arr[9] == 1", {"arr": [1]})
    assert "求值失败" in str(ei.value)


def test_allowed_const_types():
    """常量类型只放行 str/int/float/bool/None：bytes 与 complex 没有业务场景，
    多放一种就是多一个口子（complex 还能参与运算出怪值）。"""
    for literal in ("'s'", "1", "1.5", "True", "None"):
        validate_expression(literal)
    for literal in ("b'x'", "1j"):
        with pytest.raises(ConditionSyntaxError) as ei:
            validate_expression(literal)
        assert "不支持的常量类型" in str(ei.value)


def test_max_expr_length_constant_is_enforced():
    """长度上限本身是个常量，断言它的存在避免以后被随手调大。"""
    assert safe_eval.MAX_EXPR_LENGTH == 2000
