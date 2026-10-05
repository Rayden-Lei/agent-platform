from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import Agent, ApiKey, Conversation, Message, User

CHANNEL_UI = "ui"
CHANNEL_API = "api"
CHANNEL_SHARE = "share"
# 会话通道 → 运行记录的来源（run_service.RUN_SOURCES）
RUN_SOURCE_OF = {CHANNEL_UI: "chat", CHANNEL_API: "api_key", CHANNEL_SHARE: "share"}


# ---------- 会话通道与归属（docs/15 3.7.1、3.6）：全仓只有这一处判定，对话、/conversations、分享访客都走它 ----------

@dataclass(frozen=True)
class Caller:
    """会话的调用方：通道 + 归属。会话只属于这五项与它完全一致的调用方（建会话时也按这五项写入）——
    ui：本人在界面里；api：某个 Key（与同一个 end_user），user_id 是 Key 的归属人；
    share：某条分享链接的访客——公开模式 user_id 是分享创建者、end_user 是访客 id，"仅登录"模式 user_id 是访客本人、end_user 为空。
    2026-10-05 前只比 user_id：Key 能读删归属人在界面里的全部会话，同一个 Key 下所有终端用户的会话互相可见。"""

    channel: str
    user_id: int
    api_key_id: int | None = None
    end_user: str | None = None
    share_id: int | None = None


def check_end_user(api_key: ApiKey | None, end_user: str | None) -> None:
    """end_user 只对 API Key 生效：登录请求带了 400（界面里的会话按本人隔离，不存在"终端用户"）。"""
    if api_key is None and end_user is not None:
        raise BizError(400, "end_user 只能在 API Key 调用时传")


def caller_for(user: User, api_key: ApiKey | None = None, end_user: str | None = None) -> Caller:
    """登录用户或 API Key 请求的调用方（分享访客的见 share_service.Guest.caller）。"""
    check_end_user(api_key, end_user)
    if api_key is None:
        return Caller(CHANNEL_UI, user.id)
    return Caller(CHANNEL_API, user.id, api_key_id=api_key.id, end_user=end_user)


def owns(conv: Conversation, caller: Caller) -> bool:
    """会话是否属于该调用方：通道、用户、Key、终端用户、分享五项都一致（都为空也算一致）。"""
    return (conv.channel, conv.user_id, conv.api_key_id, conv.end_user, conv.share_id) == \
        (caller.channel, caller.user_id, caller.api_key_id, caller.end_user, caller.share_id)


def _owned_filter(query, caller: Caller):
    """列表用的同一口径（SQL 写法）；为空的项按"为空"过滤，不是"不限"——end_user 为空时只取没有终端用户的会话。"""
    pairs = ((Conversation.channel, caller.channel), (Conversation.user_id, caller.user_id), (Conversation.api_key_id, caller.api_key_id),
             (Conversation.end_user, caller.end_user), (Conversation.share_id, caller.share_id))
    return query.filter(*[column.is_(None) if value is None else column == value for column, value in pairs])


def get_owned_conversation(db: Session, conversation_id: int, caller: Caller) -> Conversation:
    """取属于该调用方的会话；不属于的一律按 404 处理，避免泄露会话存在性。"""
    conv = db.get(Conversation, conversation_id)
    if conv is None or not owns(conv, caller):
        raise BizError(404, "会话不存在")
    return conv


def owned_conversations(db: Session, caller: Caller, agent_id: int = None, q: str = None):
    """属于该调用方的会话查询（按更新时间倒序，id 作副键），列表与分享访客的会话列表共用。"""
    query = _owned_filter(db.query(Conversation), caller)
    if agent_id:
        query = query.filter(Conversation.agent_id == agent_id)
    if q:
        query = query.filter(Conversation.title.ilike(f"%{q}%"))
    return query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())


def list_conversations(db: Session, caller: Caller, params: PageParams, agent_id: int = None, q: str = None) -> dict:
    """分页列出属于该调用方的会话（登录：本人在界面里的；API Key：这个 Key 与同一个 end_user 建的），
    可按智能体过滤、按标题模糊搜索，按更新时间倒序（最近活跃在前）。
    附带消息数与智能体名：消息数用一次分组查询，智能体名用一次 IN 查询，不逐行查库。"""
    page = paginate(owned_conversations(db, caller, agent_id, q), params)
    page["items"] = _serialize(db, page["items"])
    return page


def get_conversation(db: Session, conversation_id: int, caller: Caller) -> dict:
    """单个会话，结构同列表项；不属于该调用方 404。对话页只带 conversation 深链时据此定位所属智能体。"""
    return _serialize(db, [get_owned_conversation(db, conversation_id, caller)])[0]


def _serialize(db: Session, rows: list[Conversation]) -> list[dict]:
    """会话行 → 接口结构：消息数用一次分组查询，智能体名用一次 IN 查询，不逐行查库。"""
    ids = [c.id for c in rows]
    counts = dict(db.query(Message.conversation_id, func.count(Message.id)).filter(Message.conversation_id.in_(ids)).group_by(Message.conversation_id).all()) if ids else {}
    agent_ids = {c.agent_id for c in rows if c.agent_id}
    agent_names = dict(db.query(Agent.id, Agent.name).filter(Agent.id.in_(agent_ids)).all()) if agent_ids else {}
    return [{
        "id": c.id, "agent_id": c.agent_id, "agent_name": agent_names.get(c.agent_id), "title": c.title, "summary": c.summary,
        "message_count": int(counts.get(c.id, 0)),
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    } for c in rows]


def list_messages(db: Session, conversation_id: int, caller: Caller) -> list[dict]:
    """取会话内全部消息（按 ID 升序，即对话顺序），先校验会话归属。token_usage 随消息返回，刷新后历史消息仍能显示用量。
    分享访客不走这里（会把工具入参与结果、引用的 kb_id / score、用量整包返回），用 share_service 的访客结构。"""
    get_owned_conversation(db, conversation_id, caller)
    rows = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "citations": m.citations,
            "token_usage": m.token_usage or None,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


def delete_conversation(db: Session, conversation_id: int, caller: Caller) -> None:
    """删除会话（消息随外键 CASCADE 级联删除），先校验会话归属。"""
    conv = get_owned_conversation(db, conversation_id, caller)
    db.delete(conv)
    db.commit()
