import ast
import json
from datetime import datetime
from typing import Any

import httpx

from app.db.models import Tool


async def execute_tool(tool: Tool, arguments: dict) -> dict:
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
            return {"error": str(e)}
    return {"error": f"unknown builtin tool: {name}"}


def _safe_eval(expr: str) -> Any:
    tree = ast.parse(expr, mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError("表达式仅支持数字与 + - * / **")
    return eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})


async def _execute_http(tool: Tool, args: dict) -> dict:
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
            except Exception:
                return {"result": resp.text}
    except Exception as e:
        return {"error": str(e)}
