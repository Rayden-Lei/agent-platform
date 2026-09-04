import json
import logging
from datetime import datetime

from langchain_core.tools import StructuredTool, tool

from app.db.models import Tool
from app.tools.executor import _execute_http, _safe_eval

logger = logging.getLogger(__name__)


@tool
def current_time() -> str:
    """获取当前日期和时间。"""
    return datetime.now().isoformat()


@tool
def calculator(expression: str) -> str:
    """计算数学表达式，仅支持数字与 + - * / ** 运算。参数 expression 为算式字符串，如 "(2+3)*4"。"""
    try:
        return str(_safe_eval(expression))
    except Exception as e:
        # 错误信息回给模型让它自己纠正，同时留痕：模型反复传错格式时能被发现
        logger.warning("calculator 工具计算失败：expression=%r error=%s", expression, e)
        return f"计算错误: {e}"


def _build_http_tool(t: Tool):
    async def _run(arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError as e:
            # 模型给的参数不是合法 JSON：按空参数调用，但要记下来，否则表现为"工具总是没带参数"
            logger.warning("工具 %s 的参数不是合法 JSON，按空参数调用：%s", t.name, e)
            args = {}
        result = await _execute_http(t, args)
        return json.dumps(result, ensure_ascii=False)

    return StructuredTool.from_function(
        name=t.name,
        description=t.description,
        coroutine=_run,
    )


def build_tools(tool_dbs: list) -> list:
    tools = [current_time, calculator]
    for t in tool_dbs:
        if t.type == "http":
            tools.append(_build_http_tool(t))
    return tools
