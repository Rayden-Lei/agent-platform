"""工作流对话（docs/17 §3.1 / §3.4，方案 c）：一句话触发一次工作流运行，会话只做历史展示。

为什么是方案 c（每轮独立 run）而不是把历史拼进入参：工作流是"输入 → 输出"的一次性函数，没有对话状态；
把历史字符串拼进 input 是最容易埋坑的做法（谁拼、拼多少条、超长怎么截全是隐式约定，docs/17 §3.4 已判定不做）。
需要上下文的工作流应当自己声明输入变量，由调用方逐轮填。

一句话怎么变成入参：
- 消息填给"消息变量"：文本变量里名为 input 的优先，否则文本变量只有一个时就用它；
- 其余变量取声明里的默认值（没有默认值的必填变量无法自动填，直接 400 并说明是哪个）；
- 一个可用的文本变量都没有时不能作为对话目标，同样 400。前端按同一规则判断并禁用输入框。

事件映射（docs/17 §3.5）：节点完成 → tool_call + tool_result、最终输出 → delta、失败 → error。
刻意不新增 node 事件类型：前端 switch 与三处 transport 都要改，收益只是"更准确"。
"""
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.limits import TOOL_RESULT_PREVIEW_CHARS
from app.db.models import Workflow
from app.services import chat_turn, workflow_service
from app.services.conversation_service import KIND_WORKFLOW, Caller
from app.workflow.io_contract import build_initial_state, start_variables

logger = logging.getLogger(__name__)

# 约定用作文本输入的变量名：有它就用它，没有时退到"唯一的文本变量"
MESSAGE_VARIABLE = "input"

# 工作流输出里优先当成"回答"的键：声明了同名的结束输出就直接用它
REPLY_KEYS = ("reply", "answer", "text", "content", "output")

# 节点类型的中文名。与前端 constants/status.ts 的 NODE_TYPE_LABEL 同一套说法，
# 但这里是"事件里给人看的节点名"，后端自己产事件就得自己带，不能指望前端反查。
NODE_LABELS = {
    "start": "开始", "end": "结束", "agent": "智能体", "tool": "工具", "condition": "条件",
    "kb_retrieval": "知识库检索", "code": "代码执行", "http": "HTTP 请求", "loop": "循环",
    "human_review": "人工审核", "parallel": "并行", "join": "汇聚",
}


def message_variable(graph: dict) -> tuple[str | None, str]:
    """选出承载用户消息的变量，返回 (变量名, 不可用的原因)。

    规则只写这一处，前端按同一套逻辑判断能否作为对话目标——两边各写一套就会出现
    "前端让发、后端 400"或反过来的情况。
    """
    texts = [v for v in start_variables(graph) if v.type == "text"]
    named = next((v for v in texts if v.name == MESSAGE_VARIABLE), None)
    if named is not None:
        return named.name, ""
    if len(texts) == 1:
        return texts[0].name, ""
    if not texts:
        return None, "该工作流的开始节点没有声明文本输入变量，不能作为对话目标"
    names = "、".join(v.name for v in texts)
    return None, f"该工作流的开始节点有多个文本变量（{names}），请把其中一个改名为 {MESSAGE_VARIABLE} 后再对话"


def build_inputs(graph: dict, message: str) -> dict:
    """按声明把一条消息拼成完整入参：消息变量用消息，其余用默认值；还有必填的没默认值就 400。

    这正是"只用填该填的东西"的边界：工作流自己把某个变量声明成必填，就必须有人提供，
    平台不会替你猜一个值。
    """
    name, reason = message_variable(graph)
    if name is None:
        raise BizError(400, reason)
    values: dict[str, Any] = {}
    missing: list[str] = []
    for var in start_variables(graph):
        if var.name == name:
            values[var.name] = message
        elif var.default is not None:
            values[var.name] = var.default
        else:
            missing.append(var.name)
    if missing:
        raise BizError(400, f"工作流还有必填变量没有默认值（{'、'.join(missing)}），无法用一句话触发；"
                            "请给它们设默认值，或改用运行弹窗逐个填写")
    return values


def prepare_workflow_chat(db: Session, caller: Caller, workflow_id: int, message: str, conversation_id: int | None = None,
                          client_message_id: str | None = None):
    """校验工作流与入参并建会话与运行记录。返回 (PreparedTurn, None) 或 (None, ReplayChat)。

    拒绝都在写库之前：消息全空白 400、工作流不存在 404、图不合法 400、没有可用作文本输入的变量 400、
    还有必填变量没默认值 400。入参在这里就算好，运行记录里记的就是实际会传下去的那份，
    事后能从运行记录回答"这句话被填到了哪个变量"。
    """
    chat_turn.validate_message(message)
    workflow = workflow_service.get_workflow(db, workflow_id)
    workflow_service.check_graph(workflow.graph)
    inputs = build_inputs(workflow.graph, message)
    return chat_turn.open_turn(
        db, caller, KIND_WORKFLOW, workflow_id, message, conversation_id, client_message_id,
        missing_detail="会话不存在或不属于该工作流", run_type="workflow",
        input_data={"message": message, "inputs": inputs}, extra={"inputs": inputs},
    )


def mark_awaiting_review(db: Session, run_id: int, content: str, outputs: list) -> None:
    """人工审核节点暂停时的收尾：运行记录置 awaiting_review（不是终态，不写 finished_at），
    与 workflow_service.execute_workflow 同一口径。审批走运行记录页的 resume，由那条路径接着跑完并收尾。
    已经生成的部分回答照常落库（在调用方写），这里只动运行记录。"""
    from app.db.models import Run

    run = db.get(Run, run_id)
    if run is None:
        return
    run.status = "awaiting_review"
    run.output = {"content": content, "outputs": outputs}
    db.commit()


def load_workflow(db: Session, workflow_id: int) -> Workflow:
    """执行时再取一次工作流行：准备阶段到执行阶段之间图可能被改过，按最新的跑。"""
    return workflow_service.get_workflow(db, workflow_id)


def initial_state(graph: dict, inputs: dict) -> dict:
    """首跑 state：与 POST /run 走同一个构造函数，入参规则不可能两边不一致。"""
    return build_initial_state(graph, inputs)


def _node_detail(node_type: str, config: dict) -> str:
    """节点的可读说明，尽量用用户自己填过的东西（工具名、URL、审核说明），没有就不加后缀。"""
    if node_type == "tool":
        return str(config.get("tool_name") or "")
    if node_type == "http":
        return str(config.get("url") or "")
    if node_type == "condition":
        return str(config.get("expression") or "")
    if node_type == "human_review":
        return str(config.get("instruction") or "")
    return ""


def node_step(graph: dict, node_id: str, delta: dict) -> dict:
    """一个节点完成时的事件内容：{label, preview, status, line}。

    label 是 tool_call 的名字（用户看到的节点卡片标题），preview 是 tool_result 的内容（截断到展示口径），
    line 是给"最终回答"用的轨迹一行（节点失败会直接让整张图抛错、走不到这里，所以状态只有 done）。
    """
    node = next((n for n in (graph.get("nodes") or []) if n.get("id") == node_id), {})
    node_type = node.get("type") or ""
    label = NODE_LABELS.get(node_type, node_type or "节点")
    detail = _node_detail(node_type, node.get("config") or {})
    name = f"{label}·{detail}" if detail else label
    raw = delta if isinstance(delta, str) else json.dumps(delta, ensure_ascii=False, default=str)
    return {"label": name, "preview": raw[:TOOL_RESULT_PREVIEW_CHARS], "status": "done", "line": label}


def reply_of(output: Any) -> str:
    """把工作流输出变成一段回答文本：约定的 reply 类键 → 单一输出 → 纯文本 → JSON 格式化。

    工作流的输出是结构化数据、而对话要的是一段文本，这条规则不定死前端就没法渲染（docs/17 §3.4）。
    """
    if isinstance(output, dict):
        for key in REPLY_KEYS:
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value
        if len(output) == 1:
            only = next(iter(output.values()))
            if isinstance(only, str) and only.strip():
                return only
    if isinstance(output, str) and output.strip():
        return output
    if output is None:
        return ""
    return json.dumps(output, ensure_ascii=False, indent=2)


def answer_of(outputs: list, interrupted: bool) -> str:
    """这轮回答的正文：取最后一个非空的节点输出转成文本。

    节点轨迹已经作为工具卡片展示过了，不重复塞进正文（否则一段话会被说两遍）。
    人工审核中断时还没有最终输出，改为一句指引——首版不做对话内审批（docs/17 §3.6），
    审批仍在运行记录页完成。
    """
    if interrupted:
        return "该工作流在人工审核节点暂停了。请到「运行记录」里找到这次运行完成审批，审批后会继续执行。"
    for output in reversed(outputs):
        text = reply_of(output)
        if text:
            return text
    return "工作流已执行完成，但没有返回输出。"
