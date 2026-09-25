import ast
import json
import logging
import operator
from datetime import datetime

import httpx

from app.db.models import Tool

logger = logging.getLogger(__name__)


async def execute_tool(tool: Tool, arguments: dict) -> dict:
    """工具执行入口：按类型分发。

    - builtin：走内置实现（current_time / calculator）
    - 其他（http）：按 tool.config 调用外部 HTTP 接口
    返回统一 dict（{"result": ...} 或 {"error": ...}），调用方不感知底层差异；本函数为 async。
    """
    if tool.type == "builtin":
        return await _execute_builtin(tool.name, arguments)
    return await _execute_http(tool, arguments)


async def _execute_builtin(name: str, args: dict) -> dict:
    if name == "current_time":
        return {"result": datetime.now().isoformat()}
    if name == "calculator":
        expr = args.get("expression", "")
        try:
            # 白名单 AST 求值，仅允许数字与四则运算，避免任意代码执行
            result = _safe_eval(expr)
            return {"result": result}
        except Exception as e:
            # 表达式非法或除零属调用方输入问题，返回错误即可，但要留痕以便发现模型总是传错格式
            logger.warning("计算器工具执行失败：expr=%r error=%s", expr, e)
            return {"error": str(e)}
    return {"error": f"unknown builtin tool: {name}"}


# 计算器的资源上限（2026-09-25）：大整数运算在一次字节码里完成且持有 GIL，9**9**9 这类表达式会让整个后端进程停摆，
# 而内置计算器挂在每个智能体上、任何能对话的人都能诱导模型调用。所以逐节点求值，每步先估规模再算
CALC_MAX_EXPR_CHARS = 200  # 同时挡住超长乘法链与深嵌套括号（ast.parse 递归过深）
CALC_MAX_INT_BITS = 1024  # 整数中间结果上限，约 308 位十进制；浮点溢出 Python 自己会抛 OverflowError
CALC_MAX_EXPONENT = 1000
_CALC_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}
_CALC_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval(expr: str) -> int | float:
    """白名单求值：只允许整数、小数常量与 + - * / ** 运算，拒绝任意代码执行，也拒绝算不完的大数。

    不用 eval：逐节点递归求值，乘方先按"底数位数 × 指数"估结果大小，超限直接拒绝而不是算出来再判断。
    非法或超限一律抛 ValueError（除零抛 ZeroDivisionError、浮点溢出抛 OverflowError），由调用方转成工具错误。
    """
    if len(expr) > CALC_MAX_EXPR_CHARS:
        raise ValueError(f"表达式过长（上限 {CALC_MAX_EXPR_CHARS} 字符）")
    return _calc_node(ast.parse(expr, mode="eval").body)


def _calc_node(node: ast.AST) -> int | float:
    # type() 精确匹配：bool 是 int 的子类、复数与字符串常量都不放行（'a'*10**9 能吃掉 1GB 内存）
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _calc_checked(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_UNARY_OPS:
        return _CALC_UNARY_OPS[type(node.op)](_calc_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_BIN_OPS:
        left, right = _calc_node(node.left), _calc_node(node.right)
        if isinstance(node.op, ast.Pow):
            _calc_check_pow(left, right)
        return _calc_checked(_CALC_BIN_OPS[type(node.op)](left, right))
    raise ValueError("表达式仅支持数字与 + - * / **")


def _calc_check_pow(base: int | float, exponent: int | float) -> None:
    if abs(exponent) > CALC_MAX_EXPONENT:
        raise ValueError(f"指数过大（上限 {CALC_MAX_EXPONENT}）")
    if isinstance(base, int) and isinstance(exponent, int) and exponent > 0 and abs(base).bit_length() * exponent > CALC_MAX_INT_BITS * 2:
        raise ValueError("结果过大")


def _calc_checked(value: int | float | complex) -> int | float:
    if isinstance(value, complex):
        raise ValueError("结果不是实数")
    if isinstance(value, int) and value.bit_length() > CALC_MAX_INT_BITS:
        raise ValueError("结果过大")
    return value


async def _execute_http(tool: Tool, args: dict) -> dict:
    """按工具配置调用外部 HTTP 接口。

    - method=GET：参数走 query；其他方法：参数作为 JSON body
    - 响应优先按 JSON 解析返回；非 JSON（纯文本/HTML）按 {"result": 文本} 返回
    - 网络/HTTP 错误不抛出，返回 {"error": ...} 并记日志，交由上层（工作流/Agent）继续处理
    """
    cfg = tool.config or {}
    method = str(cfg.get("method") or "POST").upper()
    url = cfg.get("url")
    headers = cfg.get("headers") or {}
    timeout = tool.timeout or 30
    if not url:
        return {"error": "工具未配置 URL"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(url, params=args, headers=headers)
            else:
                resp = await client.request(method, url, json=args, headers=headers)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                # 对方返回的不是 JSON（纯文本/HTML），按文本返回是预期行为
                return {"result": resp.text}
    except httpx.HTTPError as e:
        logger.warning("HTTP 工具调用失败 tool=%s method=%s url=%s error=%s", tool.name, method, url, e)
        return {"error": str(e)}
    except Exception as e:
        logger.exception("HTTP 工具执行异常 tool=%s method=%s url=%s", tool.name, method, url)
        return {"error": str(e)}
