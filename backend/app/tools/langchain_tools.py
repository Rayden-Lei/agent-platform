import json
import logging
from datetime import datetime

from langchain_core.tools import StructuredTool, tool
from pydantic import ValidationError

from app.core.exceptions import BizError
from app.db.models import Tool
from app.services import skill_resource
from app.services.skill_resource import SCRIPT_SUFFIXES
from app.tools.builtin import BUILTIN_PARAMETERS
from app.tools.executor import _GENERAL_HANDLERS, _call_general, _safe_eval, execute_tool
from app.tools.permission import ToolCallContext
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


def _build_run_skill_script(skills: list):
    """把本次装配的技能做成 run_skill_script 工具（docs/17 §4.5，P2.6）。

    与 load_skill 同一条白名单：只在装配时给的这些技能里找脚本，路径也必须落在该技能的
    resources 里。模型传别处的路径一律「脚本不存在」—— 不做这个限制，参数就是模型生成的，
    等于把整个对象存储变成它的文件系统。

    input 是给脚本的入参（任意 JSON），脚本从 stdin 读 {"input": ...}、把结果 JSON 打 stdout。
    """
    by_name = {s.name: s for s in skills}

    def _run(skill: str, path: str, input: str = "") -> str:
        s = by_name.get(skill)
        if s is None:
            logger.warning("run_skill_script 请求了未绑定的技能：%r（本次可用 %s）", skill, sorted(by_name))
            return f"技能不存在：{skill}"
        try:
            payload = {"input": json.loads(input) if input else None}
        except json.JSONDecodeError:
            # 模型传了非 JSON 的字符串时按纯文本给进去，比直接报错更有用；同时留痕便于发现它总是传错
            logger.info("run_skill_script 的 input 不是 JSON，按纯文本传入：%r", input[:80])
            payload = {"input": input}
        try:
            result = skill_resource.run_script(s, path, payload)
        except BizError as e:
            # 路径非法 / 脚本不在这个技能里：回给模型让它换路径，不抛异常。
            # 抛出去会被 LangGraph 标成工具 error 并中断这一轮，而这是模型可以自己纠正的输入错误。
            logger.warning("run_skill_script 拒绝 skill=%s path=%r：%s", skill, path, e.detail)
            return json.dumps({"error": e.detail}, ensure_ascii=False)
        if not result.ok:
            logger.warning("技能脚本执行失败 skill=%s path=%s mode=%s error=%s", skill, path, result.mode, result.error)
            return json.dumps({"error": result.error, "stderr": result.stderr[:1000]}, ensure_ascii=False)
        return result.output.strip() or json.dumps({"error": "脚本没有输出"}, ensure_ascii=False)

    return StructuredTool.from_function(
        name="run_skill_script",
        description=(
            "执行某个技能自带的脚本（仅 .py）。参数 skill 取【可用技能】里的名字，path 是该技能资源里的脚本文件名，"
            "input 是传给脚本的入参（字符串，会作为 JSON 解析）。脚本从 stdin 读 {\"input\": ...}、把结果 JSON 打到 stdout。"
        ),
        func=_run,
    )


def _build_load_skill(skills: list):
    """把本次装配的技能做成 load_skill 工具（docs/17 §4.4 第 2 条）。

    白名单在装配时定死：闭包里只有这些技能，模型传别的名字一律「技能不存在」。
    不在执行时查库、也不按名字全局搜 —— 那样等于给模型一个读全库技能的越权入口。
    技能正文装配时已经取过（目录与常驻正文都要用），这里复用同一份，不多查一次库。
    """
    by_name = {s.name: s for s in skills}

    def _load(name: str) -> str:
        s = by_name.get(name)
        if s is None:
            # 不区分「不存在」与「没绑定」：区分了等于告诉模型哪些技能存在但读不到，把清单泄露出去
            logger.warning("load_skill 请求了未绑定的技能：%r（本次可用 %s）", name, sorted(by_name))
            return f"技能不存在：{name}"
        return s.content

    return StructuredTool.from_function(
        name="load_skill",
        description="加载一份操作手册的正文。遇到【可用技能】目录里列出的任务时先调用它取正文，再按里面的步骤做。参数 name 取目录里列出的名字。",
        func=_load,
    )


def _build_http_tool(t: Tool, ctx: ToolCallContext | None = None):
    """把 DB 中的 HTTP 工具转成 LangChain StructuredTool（FR-030）。

    按 config.parameters 生成 args_schema，模型看到参数名 / 类型 / 必填 / 枚举并以结构化参数调用；
    未声明参数的工具暴露为无参数工具，模型只能以 {} 调用。
    参数不符合声明时不抛异常中断对话：校验错误作为工具结果回给模型让它纠正，同时打 WARN 留痕。
    ctx 是这次装配的来源（对话 / 调试 / 分享），执行闸门据此判定（docs/16 P3a）。
    """
    try:
        parameters = parse_parameters(t.config)
    except ValidationError as e:
        # 库里的声明不合法（绕过接口直接写库）：按无参数工具暴露，不让一个坏工具拖垮整个对话
        logger.warning("工具 %s 的参数声明不合法，按无参数工具暴露：%s", t.name, format_validation_error(e))
        parameters = ToolParameters()

    async def _run(**kwargs) -> str:
        # 走 execute_tool 而不是 _execute_http：闸门在 execute_tool 的中间件链里，
        # 直调 _execute_http 会绕过它（docs/16 P1 第 3 步把两条入口合成一条）。
        # LangChain 会把可选参数的默认 None 一并传进来，不过滤会变成 ?days= 这种空查询参数
        result = await execute_tool(t, {k: v for k, v in kwargs.items() if v is not None}, ctx)
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


# 能力型内置工具给模型看的说明。写清"什么时候用它"比写清"它做什么"更能减少误调用。
TOOL_DESCRIPTIONS: dict[str, str] = {
    "text_stats": "统计一段文本的字符数、词数与行数。需要知道长度、字数或行数时用。",
    "random_int": "生成指定区间内的随机整数。抽奖、随机编号、模拟数据时用。",
    "random_choice": "从若干候选项里随机挑一个。候选项用换行或英文逗号分隔。",
    "base64_encode": "把文本编码成 base64 字符串。",
    "base64_decode": "把 base64 字符串解码回文本。",
    "json_query": "按点路径从 JSON 文档里取值，如 data.items[0].name。处理接口返回、配置文件等 JSON 时用。",
    "http_request": "发起一次 HTTP 请求（GET/POST/PUT/DELETE/PATCH/HEAD）并返回状态码与响应体。需要访问外部接口时用；不能访问内网地址。",
    "web_search": "联网搜索网页，返回标题、链接、站点、日期与摘要片段。需要查实时信息、新闻或不确定的事实时用。",
}
def _build_optional_builtin(name: str, tool=None):
    """把能力型内置工具包装成 LangChain StructuredTool（tools/general.py 里的实现）。

    参数声明取自 builtin.BUILTIN_PARAMETERS，与工具页展示的同一份，避免两处不一致。
    未知的 name 返回 None（库里残留了已删掉的工具名时不至于让整轮装配炸掉）。
    """
    entry = _GENERAL_HANDLERS.get(name)
    if entry is None:
        logger.warning("未知的内置工具名，跳过装配：%s", name)
        return None
    fn, _is_async = entry
    params = BUILTIN_PARAMETERS.get(name) or {"type": "object", "properties": {}, "required": []}

    async def _run(**kwargs) -> str:
        # 走与工具页 / 工作流同一条实现，不重复写一遍逻辑；
        # 工具行一并传下去，配置与凭据从它身上取（配置属于工具，不属于系统）
        try:
            result = await _call_general(entry, {k: v for k, v in kwargs.items() if v is not None}, tool=tool)
        except Exception as e:
            logger.exception("内置工具 %s 执行失败", name)
            return json.dumps({"error": f"工具执行失败：{e}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    return StructuredTool.from_function(
        name=name,
        description=TOOL_DESCRIPTIONS[name],
        coroutine=_run,
        args_schema=build_args_model(ToolParameters(**params), f"{name}_args"),
    )


def build_tools(tool_dbs: list, *, source: str = "chat", agent_id: int | None = None, run_id: int | None = None,
                skills: list | None = None) -> list:
    """组装 Agent 可用的工具列表：内置工具（current_time/calculator）恒有，DB 中启用的 http 类型工具追加进来。
    停用的工具仍绑定在智能体上，但不暴露给模型（工具页的启停开关就是靠这里生效）。

    source / agent_id / run_id 在装配时定死、随工具对象带进一次对话，执行时不再猜：一次对话的来源不会
    中途变化，而执行那一刻（模型决定调用哪个工具）拿不到可靠的来源信息，只能靠闭包提前传进来。
    它们不影响暴露哪些工具，只用于执行闸门判定与拒绝留痕（docs/16 P3a）。

    skills 是本次装配的已启用技能行（docs/17 §4）：非空时追加 load_skill，白名单就是这份列表。
    不传或空列表时不追加 —— 没绑技能的智能体不该看到一个永远返回「技能不存在」的工具，那只会诱导模型乱试。
    """
    tools = [current_time, calculator]
    for t in tool_dbs:
        if not t.is_enabled:
            # 停用的工具仍绑在智能体上，但不暴露给模型（工具页的启停开关靠这里生效）
            continue
        if t.type == "builtin":
            # 能力型内置工具（text_stats / web_search 等）：按 name 从分发表取实现，
            # 由 LangChain 包装成 StructuredTool，参数声明来自 builtin.BUILTIN_PARAMETERS
            wrapped = _build_optional_builtin(t.name, t)
            if wrapped is not None:
                tools.append(wrapped)
            continue
        tools.append(_build_http_tool(t, ToolCallContext(tool=t, source=source, agent_id=agent_id, run_id=run_id)))
    if skills:
        tools.append(_build_load_skill(skills))
        # 只有真的登记了 .py 资源的技能才给执行工具：一个永远返回「脚本不存在」的工具只会诱导模型乱试
        if any(r.get("name", "").endswith(SCRIPT_SUFFIXES) for s in skills for r in (s.resources or [])):
            tools.append(_build_run_skill_script(skills))
    return tools
