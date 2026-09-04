import ast
import json
import logging
from datetime import datetime
from typing import Any

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


def _safe_eval(expr: str) -> Any:
    """AST 白名单求值：只允许数字常量与 + - * / ** 运算，拒绝任意代码执行。

    逐节点校验语法树类型，白名单之外一律抛 ValueError；随后在空命名空间里 eval。
    """
    tree = ast.parse(expr, mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError("表达式仅支持数字与 + - * / **")
    return eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})


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
