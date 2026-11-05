"""对话分类型的公共部分（docs/17 §3，P1）：三种对话共用一套会话归属、幂等回放与运行记录。

这里只放"三种类型完全一样"的逻辑：校验消息与调用方、取/建会话、落用户消息与运行记录、幂等回放。
各类型的差异（配置从哪来、怎么执行）在各自的 prepare_* / 执行器里，不写进本模块，
否则又会变成一个大函数里塞三种分支（docs/17 §9.1 的风险 1）。

会话的 kind 与归属列（agent_id / workflow_id / model_id）在建会话时一次写定，之后不可变：
续聊时既要校验归属，也要校验类型与目标一致——否则模型对话能接着写智能体会话。
"""
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import BizError
from app.db.models import ApiKey, Conversation, Message, Run
from app.services import run_service
from app.services.conversation_service import KIND_AGENT, KIND_WORKFLOW, RUN_SOURCE_OF, TARGET_COLUMN, Caller, owns


class ReplayChat(NamedTuple):
    """同一会话里重复的 client_message_id：不落消息、不调模型，回放首次的结果（docs/15 3.7.1 幂等）。

    status 为 success 时带首次回答（message_id / content / citations / usage）；failed、cancelled 时带 error。
    三种对话共用这一种回放结构：它们都是一轮一条运行记录 + 一条回答消息，回放不需要按类型分叉。
    """

    conversation_id: int
    run_id: int | None
    status: str
    message_id: int | None = None
    content: str = ""
    citations: list | None = None
    usage: dict | None = None
    error: str | None = None


@dataclass(frozen=True)
class PreparedTurn:
    """一轮对话写库的结果：会话、运行记录、这轮回答要用的配置版本号（只有智能体对话有），
    以及各类型自己的执行参数（extra：工作流对话放已经算好的 inputs，执行时不再重算，
    避免"准备阶段算出的入参"和"实际传下去的入参"在两次计算之间产生分歧）。"""

    conversation_id: int
    run_id: int
    agent_version: int | None = None
    extra: dict | None = None


def target_of(conv: Conversation) -> int | None:
    """会话指向的对象 id（模型 / 智能体 / 工作流），按 kind 取对应列。"""
    return getattr(conv, TARGET_COLUMN[conv.kind], None)


def validate_message(message: str) -> None:
    """消息不能全是空白。长度与字符集由路由的请求体模型管（422），这里只做服务层的最后一道判定。"""
    if not message.strip():
        raise BizError(400, "消息不能为空")


def resume_conversation(db: Session, caller: Caller, conversation_id: int, kind: str, target_id: int,
                        missing_detail: str) -> Conversation:
    """续聊时取会话并校验三件事：属于该调用方、类型一致、指向的对象一致。

    三样都核对才返回，否则一律 404 —— 不区分"不属于你"与"不属于这个对象"，
    避免拿会话 id 探测别人的会话是否存在（与 conversation_service.get_owned_conversation 同一口径）。
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None or not owns(conv, caller) or conv.kind != kind or target_of(conv) != target_id:
        raise BizError(404, missing_detail)
    return conv


def _replay_of(db: Session, conversation_id: int, client_message_id: str):
    """同一会话里这个 client_message_id 首次的结果；没发过返回 None。首次还在生成 → 409。

    幂等回放（docs/15 3.7.1）对三种对话一视同仁：模型对话与工作流对话也是"一轮一条运行记录 + 一条回答消息"，
    所以回放逻辑不需要按类型分叉。
    """
    first = db.query(Message).filter(Message.conversation_id == conversation_id, Message.client_message_id == client_message_id,
                                     Message.role == "user").first()
    if first is None:
        return None
    run = db.get(Run, first.run_id) if first.run_id else None
    if run is None:
        return ReplayChat(conversation_id, None, "failed", error="上次请求的运行记录已不存在，请换一个 client_message_id 重试")
    if run.status not in run_service.FINAL_STATUSES:
        raise BizError(409, "该消息正在处理，请稍后用同一个 client_message_id 重试")
    # awaiting_review 也算"这轮已经答完"：工作流停在人工审核节点时运行记录不是终态（审批后还会继续），
    # 但对话这一轮已经结束、回答已经落库。当成"仍在生成"会让同一个 client_message_id 永远 409。
    if run.status in ("success", "awaiting_review"):
        answer = db.query(Message).filter(Message.run_id == run.id, Message.role == "assistant").first()
        return ReplayChat(conversation_id, run.id, "success", message_id=answer.id if answer else None,
                          content=answer.content if answer else "", citations=(answer.citations or []) if answer else [], usage=run.token_usage)
    error = run.error or ("上次请求已中断（已生成的部分见会话消息）" if run.status == "cancelled" else "上次请求失败")
    return ReplayChat(conversation_id, run.id, run.status, error=f"{error}；如需重新生成请换一个 client_message_id")


def open_turn(db: Session, caller: Caller, kind: str, target_id: int, message: str,
              conversation_id: int | None = None, client_message_id: str | None = None, *, missing_detail: str,
              run_type: str, input_data: dict, model_id: int | None = None, agent_version: int | None = None,
              extra: dict | None = None, api_key: ApiKey | None = None):
    """取/建会话、落用户消息与运行记录，返回 (PreparedTurn, None) 或 (None, ReplayChat)。

    调用前各类型已经做完自己的校验（智能体的发布状态、模型是否可用、工作流的图与入参），
    所以这里只处理"会话与运行记录"这部分，不重复判定业务可用性。
    所有拒绝都发生在写库之前；用户消息与运行记录同一次提交，幂等回放才能靠这条关联找回首次结果。
    """
    validate_message(message)
    conversation = None
    if conversation_id:
        conversation = resume_conversation(db, caller, conversation_id, kind, target_id, missing_detail)
        if client_message_id:
            replay = _replay_of(db, conversation.id, client_message_id)
            if replay is not None:
                return None, replay
    if conversation is None:
        title = message.strip()[:settings.CHAT_TITLE_MAX_LEN] or "新对话"  # 标题取首条消息开头
        conversation = Conversation(kind=kind, user_id=caller.user_id, title=title, channel=caller.channel,
                                    api_key_id=caller.api_key_id, end_user=caller.end_user, share_id=caller.share_id,
                                    **{TARGET_COLUMN[kind]: target_id})
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    user_message = Message(conversation_id=conversation.id, role="user", content=message, client_message_id=client_message_id)
    db.add(user_message)
    try:
        db.flush()  # 先撞部分唯一索引：并发的同一条 client_message_id 在这里失败，不会先建出运行记录
    except IntegrityError:
        db.rollback()
        replay = _replay_of(db, conversation.id, client_message_id) if client_message_id else None
        if replay is None:
            raise
        return None, replay
    run = run_service.create_run(
        db, run_type, caller.user_id, agent_id=target_id if kind == KIND_AGENT else None,
        workflow_id=target_id if kind == KIND_WORKFLOW else None, model_id=model_id, conversation_id=conversation.id,
        input_data=input_data, source=RUN_SOURCE_OF[caller.channel], api_key_id=caller.api_key_id,
        share_id=caller.share_id, agent_version=agent_version, commit=False,
    )
    user_message.run_id = run.id
    db.commit()
    return PreparedTurn(conversation.id, run.id, agent_version, extra), None
