from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import Agent, ApiKey, Conversation, Message, User

CHANNEL_UI = "ui"
CHANNEL_API = "api"


# ---------- 会话通道与归属（docs/15 3.7.1）：全仓只有这一处判定，对话与 /conversations 都走它 ----------

def check_end_user(api_key: ApiKey | None, end_user: str | None) -> None:
    """end_user 只对 API Key 生效：登录请求带了 400（界面里的会话按本人隔离，不存在"终端用户"）。"""
    if api_key is None and end_user is not None:
        raise BizError(400, "end_user 只能在 API Key 调用时传")


def owns(conv: Conversation, user: User | int, api_key: ApiKey | None, end_user: str | None) -> bool:
    """会话是否属于本次调用方。登录请求：channel=ui 且是本人的；API Key 请求：channel=api、是这个 Key 建的、
    且终端用户一致（都不传也算一致）。2026-10-05 前只看 user_id：Key 能读删归属人在界面里的全部会话，
    同一个 Key 下所有终端用户的会话互相可见。"""
    user_id = user if isinstance(user, int) else user.id
    if api_key is None:
        return conv.channel == CHANNEL_UI and conv.user_id == user_id
    return conv.channel == CHANNEL_API and conv.api_key_id == api_key.id and conv.end_user == end_user


def _owned_filter(query, user: User, api_key: ApiKey | None, end_user: str | None):
    """列表用的同一口径（SQL 写法）；end_user 为空时只取没有终端用户的会话，不是"全部"。"""
    if api_key is None:
        return query.filter(Conversation.channel == CHANNEL_UI, Conversation.user_id == user.id)
    return query.filter(Conversation.channel == CHANNEL_API, Conversation.api_key_id == api_key.id,
                        Conversation.end_user.is_(None) if end_user is None else Conversation.end_user == end_user)


def _get_owned_conversation(db: Session, conversation_id: int, user: User, api_key: ApiKey | None = None, end_user: str | None = None) -> Conversation:
    """取属于本次调用方的会话；不属于的一律按 404 处理，避免泄露会话存在性。"""
    check_end_user(api_key, end_user)
    conv = db.get(Conversation, conversation_id)
    if conv is None or not owns(conv, user, api_key, end_user):
        raise BizError(404, "会话不存在")
    return conv


def list_conversations(db: Session, user: User, params: PageParams, agent_id: int = None, q: str = None,
                       api_key: ApiKey | None = None, end_user: str | None = None) -> dict:
    """分页列出属于本次调用方的会话（登录：本人在界面里的；API Key：这个 Key 与同一个 end_user 建的），
    可按智能体过滤、按标题模糊搜索，按更新时间倒序（最近活跃在前）。
    附带消息数与智能体名：消息数用一次分组查询，智能体名用一次 IN 查询，不逐行查库。"""
    check_end_user(api_key, end_user)
    query = _owned_filter(db.query(Conversation), user, api_key, end_user)
    if agent_id:
        query = query.filter(Conversation.agent_id == agent_id)
    if q:
        query = query.filter(Conversation.title.ilike(f"%{q}%"))
    query = query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    page = paginate(query, params)
    page["items"] = _serialize(db, page["items"])
    return page


def get_conversation(db: Session, conversation_id: int, user: User, api_key: ApiKey | None = None, end_user: str | None = None) -> dict:
    """单个会话，结构同列表项；不属于本次调用方 404。对话页只带 conversation 深链时据此定位所属智能体。"""
    return _serialize(db, [_get_owned_conversation(db, conversation_id, user, api_key, end_user)])[0]


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


def list_messages(db: Session, conversation_id: int, user: User, api_key: ApiKey | None = None, end_user: str | None = None) -> list[dict]:
    """取会话内全部消息（按 ID 升序，即对话顺序），先校验会话归属。token_usage 随消息返回，刷新后历史消息仍能显示用量。"""
    _get_owned_conversation(db, conversation_id, user, api_key, end_user)
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


def delete_conversation(db: Session, conversation_id: int, user: User, api_key: ApiKey | None = None, end_user: str | None = None) -> None:
    """删除会话（消息随外键 CASCADE 级联删除），先校验会话归属。"""
    conv = _get_owned_conversation(db, conversation_id, user, api_key, end_user)
    db.delete(conv)
    db.commit()
