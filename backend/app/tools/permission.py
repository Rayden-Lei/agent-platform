"""工具执行闸门（docs/16 P3a）：每次调用前按来源与目标地址判定 allow / deny。

为什么不照搬 AgentScope 的规则引擎 + 五种权限模式：本平台的调用方只有登录对话、API Key、
分享访客、工作流、管理员测试五类，判定是固定的几条，不需要规则表；真出现写操作类工具
（付款、下单、发消息）再上 HITL 与规则。

只做 deny，不做 ask：
- deny 时返回 `{"error": ..., "denied": True}`，模型看到错误可以换路，事件里 tool_result
  的 state 是 denied、落库的 tool_calls.status 也是 denied，审计另有记录
- 不阻断对话，也不抛异常（抛异常会让 LangGraph 把工具标成 error，丢掉 denied 语义）
"""
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from app.db.models import Tool

logger = logging.getLogger(__name__)

# 允许的来源：对话（登录）、API Key、分享访客、装配页调试、工作流、定时任务、工具页的管理员测试
SOURCES = ("chat", "api_key", "share", "debug", "workflow", "schedule", "admin_test")


@dataclass(frozen=True)
class ToolCallContext:
    """一次工具调用的上下文。agent_id / run_id 只用于留痕，判定不依赖它们。"""

    tool: Tool
    source: str
    agent_id: int | None = None
    run_id: int | None = None


def check(ctx: ToolCallContext) -> tuple[str, str | None]:
    """返回 (decision, reason)。decision 为 allow / deny；reason 在 allow 时可能是一条提示（记日志用），
    在 deny 时是给模型看的不可用原因。

    判定顺序是有意排的，从"最不需要看配置"到"最需要看配置"，每一步的理由：

    1. 停用先判：is_enabled 是工具能不能用的唯一权威。对话装配层已经过滤、工作流引擎也单独查过，
       这里再兜一次是为了以后新增入口（定时任务、批处理）不会再漏。
    2. 内置工具直接放行：只有 current_time 与 calculator（白名单 AST 求值），没有网络、没有副作用，
       也就没有 URL 可查白名单。
    3. admin_test 跳过白名单：管理员正在配这个工具，白名单通常还没填好，拦住就永远配不出来；
       这个入口本身是 admin / developer 专属，风险由角色兜底，不是靠地址。
    4. share 在地址校验之前拦：分享链接是公网可访问的入口，装配层虽然默认不给访客装 HTTP 工具，
       但那是"装配时"的判断；万一配置被改或以后有别的装配路径，这里必须再挡一层，不能靠上游。
    5. 最后才看白名单：只看 host、不看路径与查询参数——模型能改的是参数，改不了工具配置里的地址。
       空名单是拒绝（2026-10-26 起）：没配白名单就无从判断目标是否可信，放过等于闸门不存在；
       过渡期的"放行 + WARN"只在 2026-10-26 之前存在（详见实现记录）。
    """
    tool = ctx.tool
    if not tool.is_enabled:
        return "deny", f"工具已停用：{tool.name}"
    if tool.type == "builtin":
        return "allow", None
    if ctx.source == "admin_test":
        return "allow", "管理员测试调用，跳过目标地址白名单"
    if ctx.source == "share":
        return "deny", f"分享链接不开放外部工具：{tool.name}"

    cfg = tool.config or {}
    # 过滤空串：前端清空白名单提交的是 []，而有人手工写库可能留下 [""]
    allowed = [h for h in (cfg.get("allowed_hosts") or []) if h]
    url = cfg.get("url")
    host = (urlparse(url).hostname or "") if url else ""
    if not allowed:
        # 2026-10-26 收口：过渡期结束，没配白名单的 HTTP 工具一律拒绝。
        # 之前是"放行 + 每次 WARN"（给存量工具留补配置的窗口），窗口关掉后还放行等于这道闸门不存在；
        # 只有 admin_test 例外（在上面提前返回），管理员仍能测未配白名单的工具，否则新工具永远配不出来。
        return "deny", f"工具 {tool.name} 未配置 allowed_hosts，无法判断目标地址是否可信"
    # 后缀匹配而不是精确匹配：api.example.com 要能覆盖 v2.api.example.com，
    # 但必须带点前缀，否则 "notapi.example.com" 会被 "api.example.com" 误放行
    if any(host == item or host.endswith("." + item) for item in allowed):
        return "allow", None
    return "deny", f"工具目标地址不在白名单内：{host or '（未配置 URL）'}"


def log_decision(ctx: ToolCallContext, decision: str, reason: str | None) -> None:
    """把放行提示与被拒都记到日志：被拒要能追到是哪次运行、哪个来源。"""
    if decision == "deny":
        logger.warning("工具调用被拒绝 tool=%s source=%s agent=%s run=%s：%s",
                       ctx.tool.name, ctx.source, ctx.agent_id, ctx.run_id, reason)
    elif reason:
        logger.warning("工具放行但需留意 tool=%s source=%s run=%s：%s", ctx.tool.name, ctx.source, ctx.run_id, reason)
