"""工作流表达式的受限求值器：只认比较、逻辑、算术与字面量，不执行任意代码。

为什么不能用 eval
----------------
改造前条件节点是 eval(expr, {"__builtins__": {}}, ns)。{"__builtins__": {}} 只挡住
裸的 __builtins__ 名字，挡不住 Python 的对象图 —— 从一个空元组就能走到每一个类：

    ().__class__.__base__.__subclasses__()        → 全部子类
    取到名为 Popen 的那个类 → Popen(["/bin/echo", "x"]).wait()  → 在服务进程里执行任意命令

实测可执行（2026-11-14 审计）。而同一个图里的 code 节点走的是子进程沙箱，
等于条件节点成了唯一的越狱口，定时任务还能无人值守触发。

设计原则
--------
**白名单，不是黑名单**。只放行「求值结果确定、没有副作用、拿不到对象引用」的语法节点，
其余一律拒绝。黑名单（拦掉 __class__ / __globals__ 之类）永远列不全，白名单列得全。

这与 tools/executor.py 里计算器那套（先估规模再算、限长度与位数）是同一类问题，
但求值对象不同：那边是纯算术，这边还需要比较与布尔运算来支持条件分支。
"""
from __future__ import annotations

import ast
import operator

# 允许出现在表达式里的常量类型。刻意不含 bytes / complex：业务上没有场景，多放一种就是多一个口子
_ALLOWED_CONST = (str, int, float, bool, type(None))

# 二元运算符白名单：算术 + 比较 + 逻辑。**不含** ** —— 指数运算能让后端卡死
# （9**9**9 这类大整数运算持有 GIL，docs/15 RS-16 记录过内置计算器的同类事故）
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}

# 比较运算符白名单：条件表达式最常见的就是这些
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}

# 允许调用的内置函数：都要求返回值可预期、不接触对象图
_ALLOWED_FUNCS = {
    "str": str, "len": len, "int": int, "float": float, "bool": bool,
    "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
}

# 表达式长度上限：超长表达式即使合法也没有业务意义，只会拖慢求值
MAX_EXPR_LENGTH = 2000


class ConditionSyntaxError(ValueError):
    """表达式不合法（语法错、用了不允许的语法、或类型对不上）。调用方据此返回 422 或按 false 处理。"""


def _div_guard(func, a, b):
    """除法与取模的除零保护：条件里写 x/0 是笔误，不该让整个运行抛 ZeroDivisionError。"""
    if b == 0:
        raise ConditionSyntaxError("表达式里出现了除以 0")
    return func(a, b)


def validate_expression(expr: str) -> None:
    """只做语法与白名单检查，不求值。保存图时调用，把写错的表达式挡在入库之前。

    Raises:
        ConditionSyntaxError: 语法错误、用了白名单外的语法、或表达式过长。
    """
    if not isinstance(expr, str):
        raise ConditionSyntaxError("表达式必须是字符串")
    if len(expr) > MAX_EXPR_LENGTH:
        raise ConditionSyntaxError(f"表达式过长（{len(expr)} 字符，上限 {MAX_EXPR_LENGTH}）")
    if not expr.strip():
        raise ConditionSyntaxError("表达式为空")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ConditionSyntaxError(f"语法错误：{e.msg}") from e
    _check_node(tree.body)


def _check_node(node: ast.AST) -> None:
    """递归检查整棵树：任何不在白名单里的节点都直接拒绝，并指出是哪一类语法。

    先整棵校验再求值（而不是边求值边判断），这样保存时就能给出准确报错，
    不用等到某个分支真的跑到才暴露。
    """
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, _ALLOWED_CONST):
            raise ConditionSyntaxError(f"不支持的常量类型：{type(node.value).__name__}")
        return
    # 变量引用：只允许裸名字（从传入的命名空间取值），不允许属性访问
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN_OPS:
            raise ConditionSyntaxError(f"不支持的运算符：{type(node.op).__name__}")
        _check_node(node.left)
        _check_node(node.right)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            raise ConditionSyntaxError(f"不支持的一元运算符：{type(node.op).__name__}")
        _check_node(node.operand)
        return
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise ConditionSyntaxError(f"不支持的逻辑运算符：{type(node.op).__name__}")
        for value in node.values:
            _check_node(value)
        return
    if isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _CMP_OPS:
                raise ConditionSyntaxError(f"不支持的比较运算符：{type(op).__name__}")
        _check_node(node.left)
        for comparator in node.comparators:
            _check_node(comparator)
        return
    if isinstance(node, ast.Call):
        # 只允许「裸函数名 + 参数」这一种调用形态，且函数名必须在白名单里。
        # 不允许属性调用（a.b() 能拿到任意方法）、不允许 *args / **kwargs 展开。
        if not isinstance(node.func, ast.Name):
            raise ConditionSyntaxError("不允许调用属性方法，只能调用内置函数")
        if node.func.id not in _ALLOWED_FUNCS:
            raise ConditionSyntaxError(f"不支持的函数：{node.func.id}")
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise ConditionSyntaxError("不支持 *args 展开")
        if any(kw.arg is None for kw in node.keywords):
            raise ConditionSyntaxError("不支持 **kwargs 展开")
        for arg in node.args:
            _check_node(arg)
        for kw in node.keywords:
            _check_node(kw.value)
        return
    if isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            _check_node(element)
        return
    if isinstance(node, ast.Subscript):
        # 允许 ns["key"] 与 list[0] 这类取值；切片不支持（业务上没有场景）
        _check_node(node.value)
        _check_node(node.slice)
        return
    # 其余一律拒绝：Attribute（对象图逃逸的入口）、Lambda、Comprehension、Dict/Set、
    # Await、Yield、NamedExpr（海象赋值）、JoinedStr（f-string 可插表达式）等
    raise ConditionSyntaxError(f"不支持的语法：{type(node).__name__}")


def _eval_node(node: ast.AST, env: dict):
    """对已通过 _check_node 的树求值。此处不再做白名单判断（上面已整体校验过），只处理类型错误。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise ConditionSyntaxError(f"未知变量：{node.id}")
    if isinstance(node, ast.BinOp):
        func = _BIN_OPS[type(node.op)]
        left, right = _eval_node(node.left, env), _eval_node(node.right, env)
        if type(node.op) in (ast.Div, ast.Mod):
            return _div_guard(func, left, right)
        return func(left, right)
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        return +operand
    if isinstance(node, ast.BoolOp):
        # 短路求值：and 遇到假值就停，or 遇到真值就停
        if isinstance(node.op, ast.And):
            result = True
            for value in node.values:
                result = _eval_node(value, env)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = _eval_node(value, env)
            if result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, env)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, env)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        func = _ALLOWED_FUNCS[node.func.id]
        args = [_eval_node(a, env) for a in node.args]
        kwargs = {kw.arg: _eval_node(kw.value, env) for kw in node.keywords}
        return func(*args, **kwargs)
    if isinstance(node, ast.List):
        return [_eval_node(e, env) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, env) for e in node.elts)
    if isinstance(node, ast.Subscript):
        container = _eval_node(node.value, env)
        index = _eval_node(node.slice, env)
        return container[index]
    raise ConditionSyntaxError(f"不支持的语法：{type(node).__name__}")


def evaluate(expr: str, env: dict):
    """求值。先整棵校验再求值，两步都不碰对象的属性与方法（那是逃逸的唯一入口）。

    Args:
        expr: 表达式文本。
        env: 允许出现在表达式里的变量，如 {"input": {...}, "loop_index": 3}。

    Raises:
        ConditionSyntaxError: 语法/白名单不通过，或求值期出现类型错误、除零、越界。
    """
    validate_expression(expr)
    tree = ast.parse(expr, mode="eval")
    try:
        return _eval_node(tree.body, env)
    except ConditionSyntaxError:
        raise
    except (TypeError, ValueError, KeyError, IndexError, AttributeError) as e:
        # 类型对不上（如 "abc" > 1）属于表达式写错，统一收口成同一个异常，
        # 调用方（条件节点）按 false 处理并记 WARN，不让它变成运行失败
        raise ConditionSyntaxError(f"求值失败：{e}") from e
