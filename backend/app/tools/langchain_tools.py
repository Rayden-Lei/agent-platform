import json
import logging
from datetime import datetime

from langchain_core.tools import StructuredTool, tool
from pydantic import ValidationError

from app.db.models import Tool
from app.tools.executor import _execute_http, _safe_eval
from app.tools.schema import ToolParameters, build_args_model, format_validation_error, parse_parameters

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
    """把 DB 中的 HTTP 工具转成 LangChain StructuredTool（FR-030）。

    按 config.parameters 生成 args_schema，模型看到参数名 / 类型 / 必填 / 枚举并以结构化参数调用；
    未声明参数的工具暴露为无参数工具，模型只能以 {} 调用。
    参数不符合声明时不抛异常中断对话：校验错误作为工具结果回给模型让它纠正，同时打 WARN 留痕。
    """
    try:
        parameters = parse_parameters(t.config)
    except ValidationError as e:
        # 库里的声明不合法（绕过接口直接写库）：按无参数工具暴露，不让一个坏工具拖垮整个对话
        logger.warning("工具 %s 的参数声明不合法，按无参数工具暴露：%s", t.name, format_validation_error(e))
        parameters = ToolParameters()

    async def _run(**kwargs) -> str:
        # LangChain 会把可选参数的默认 None 一并传进来，不过滤会变成 ?days= 这种空查询参数
        result = await _execute_http(t, {k: v for k, v in kwargs.items() if v is not None})
        return json.dumps(result, ensure_ascii=False)

    def _on_validation_error(e: ValidationError) -> str:
        logger.warning("工具 %s 收到不符合声明的参数：%s", t.name, format_validation_error(e))
        return f"参数校验失败：{format_validation_error(e)}"

    return StructuredTool.from_function(
        name=t.name,
        description=t.description,
        coroutine=_run,
        args_schema=build_args_model(parameters, f"{t.name}_args"),
        handle_validation_error=_on_validation_error,
    )


def build_tools(tool_dbs: list) -> list:
    """组装 Agent 可用的工具列表：内置工具（current_time/calculator）恒有，DB 中 http 类型工具追加进来。"""
    tools = [current_time, calculator]
    for t in tool_dbs:
        if t.type == "http":
            tools.append(_build_http_tool(t))
    return tools
