"""模型对话（docs/17 §3.1）：直接和某个模型聊，不挂工具、不检索知识库、不经过智能体。

为什么要单独一条路：现有对话入口必须绑定"已发布智能体"，配置来自发布版本快照。试模型、比输出这类场景
没有智能体可绑，也不该为了聊天去建一个智能体。这里用同一套事件契约、同一套会话与运行记录，
只是装配出来的上下文只有"模型 + 一句中性系统提示 + 历史消息"。

刻意不做的事（docs/17 §3.6）：
- 不做历史摘要压缩：模型对话定位是短会话试模型，超长按最近 N 条截断即可（settings.CHAT_HISTORY_MAX_MESSAGES）；
- 不装配任何工具：没有工具就不会有工具轮次，也就不需要轮数守卫以外的中间件。
"""
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import BizError
from app.db.models import Conversation, Message
from app.model_gateway.gateway import build_llm
from app.runtime.agent_config import usable_model
from app.services import chat_turn
from app.services.chat_service import ChatContext
from app.services.conversation_service import KIND_MODEL, Caller

# 模型对话的系统提示：不设人设（那是智能体的事），只说清楚"你是一个通用助手"
# 留空会让部分厂商的接口行为差异较大（有的把空 system 当缺失、有的当空串），给一句中性提示更稳
DEFAULT_SYSTEM_PROMPT = "你是一个乐于助人的助手，用简洁准确的中文回答。"


def _history(db: Session, conversation_id: int, message_text: str) -> list:
    """会话历史 → langchain 消息（最近 N 条，不压缩）。本轮用户消息已落库，最后一条与它相同要去掉，
    否则模型会收到两条一样的用户消息。"""
    rows = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    if rows and rows[-1].role == "user" and rows[-1].content == message_text:
        rows = rows[:-1]
    messages = []
    for row in rows[-settings.CHAT_HISTORY_MAX_MESSAGES:]:
        if row.role == "user":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant":
            messages.append(AIMessage(content=row.content))
    messages.append(HumanMessage(content=message_text))
    return messages


def prepare_model_chat(db: Session, caller: Caller, model_id: int, message: str, conversation_id: int | None = None,
                       client_message_id: str | None = None):
    """校验模型并建会话与运行记录。返回 (PreparedTurn, None) 或 (None, ReplayChat)。

    所有拒绝都在写库之前：消息全空白 400、模型不存在或已停用 400「模型不可用」（与智能体对话同一文案）。
    运行记录 run_type=chat、带 model_id、agent_id 为空——运营统计按 model_id 归集消耗，与智能体对话一致。
    """
    chat_turn.validate_message(message)
    model = usable_model(db, model_id)
    return chat_turn.open_turn(
        db, caller, KIND_MODEL, model_id, message, conversation_id, client_message_id,
        missing_detail="会话不存在或不属于该模型", run_type="chat",
        input_data={"message": message}, model_id=model.id,
    )


def build_model_context(db: Session, model_id: int, message_text: str, conversation_id: int) -> ChatContext:
    """模型对话的上下文：模型配置（可用性再确认一次，流式执行时才被停用也要给出明确错误）、空工具、历史消息。"""
    model = usable_model(db, model_id)
    llm = build_llm(model)  # 不带智能体参数：模型对话直接用模型默认参数
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise BizError(404, "会话不存在")
    return ChatContext(model=model, llm=llm, tools=[], system_prompt=DEFAULT_SYSTEM_PROMPT, citations=[],
                       history_messages=_history(db, conversation_id, message_text))


