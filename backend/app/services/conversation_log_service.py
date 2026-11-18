"""对话日志审阅（docs/15 PB-09 / OP-06）：管理面查看全部会话，含分享访客与 API Key 发起的会话。

与 conversation_service 的分工：那里是"当前调用方自己的会话"，归属判定 owns / _owned_filter 只有那一处；
这里是管理面视图，**不做归属判定**，可见范围由路由的角色依赖（admin / developer）决定。
消息序列化复用 conversation_service.serialize_messages，不另写一份 —— 同一条消息在对话页与对话日志里的
截断口径必须一致（工具结果默认 200 字，full_tool_results 才给库里那份 ≤ 8000）。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import ApiKey, Conversation, User
from app.db.session import rows_to_dict
from app.services import conversation_service

# 默认按更新时间倒序（最近活跃在前），id 作副键保证翻页稳定；与 /conversations 的排序一致
_ORDER = (Conversation.updated_at.desc(), Conversation.id.desc())


def _filtered(db: Session, channel: str | None = None, kind: str | None = None, target_id: int | None = None,
              user_id: int | None = None, end_user: str | None = None, q: str | None = None,
              created_from: datetime | None = None, created_to: datetime | None = None):
    """列表的过滤条件（全部下推到 query）：通道、对话类型、对象、发起人、终端用户 / 访客、标题、创建时间区间。

    target_id 与 /conversations 同口径：必须同时给 kind —— 三种类型的对象 id 各占一列，
    不给 kind 就不知道该比哪一列（静默按其中一列过滤会返回错误结果，所以 400）。
    时间区间左闭右开 [created_from, created_to)：与 core.pagination.time_range 的校验口径一致，能走索引。
    """
    query = db.query(Conversation)
    if channel:
        query = query.filter(Conversation.channel == channel)
    if kind:
        query = query.filter(Conversation.kind == kind)
    if target_id is not None:
        if kind is None:
            raise BizError(400, "按对象过滤会话时必须同时指定对话类型 kind")
        query = query.filter(getattr(Conversation, conversation_service.TARGET_COLUMN[kind]) == target_id)
    if user_id is not None:
        query = query.filter(Conversation.user_id == user_id)
    if end_user is not None:
        query = query.filter(Conversation.end_user == end_user)
    if q:
        query = query.filter(Conversation.title.ilike(f"%{q}%"))
    if created_from is not None:
        query = query.filter(Conversation.created_at >= created_from)
    if created_to is not None:
        query = query.filter(Conversation.created_at < created_to)
    return query


def _target_id(conv: Conversation) -> int | None:
    """会话对象 id：按 kind 取对应的那一列（三列互斥，由 DB 约束 ck_conversations_kind 兜底）。"""
    return getattr(conv, conversation_service.TARGET_COLUMN[conv.kind], None)


def _serialize(db: Session, rows: list[Conversation]) -> list[dict]:
    """会话行 → 管理面结构：通道、归属人、API Key、终端用户 / 访客、对象名与消息数都带上，
    一眼看出"这条会话是谁的、走哪条通道、属于哪个对象"。

    关联数据一页各查一次：消息数 1 次分组查询、对象名按类型最多 3 次 IN、用户名 1 次、Key 名 1 次，
    不逐行查库。api_key_id 是 ON DELETE SET NULL：Key 删掉后会话还在，那时 api_key_name 为空。
    """
    counts = conversation_service.message_counts(db, [c.id for c in rows])
    names = conversation_service.names_of(db, rows)
    user_ids = {c.user_id for c in rows if c.user_id}
    usernames = rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()) if user_ids else {}
    key_ids = {c.api_key_id for c in rows if c.api_key_id}
    key_names = rows_to_dict(db.query(ApiKey.id, ApiKey.name).filter(ApiKey.id.in_(key_ids)).all()) if key_ids else {}
    return [{
        "id": c.id, "channel": c.channel, "kind": c.kind,
        "target_id": _target_id(c), "target_name": names.get((c.kind, _target_id(c))),
        "title": c.title, "summary": c.summary, "message_count": int(counts.get(c.id, 0)),
        "user_id": c.user_id, "username": usernames.get(c.user_id),
        "api_key_id": c.api_key_id, "api_key_name": key_names.get(c.api_key_id),
        "end_user": c.end_user, "share_id": c.share_id,
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    } for c in rows]


def list_conversation_logs(db: Session, params: PageParams, *, channel: str | None = None, kind: str | None = None,
                           target_id: int | None = None, user_id: int | None = None, end_user: str | None = None,
                           q: str | None = None, created_from: datetime | None = None,
                           created_to: datetime | None = None) -> dict:
    """分页列出全部会话（含分享访客与 API Key 的），按更新时间倒序；可按通道、类型、对象、发起人、
    终端用户、标题、创建时间区间过滤。列表本身不写审计（逐条记会把审计页刷满），
    看具体会话内容才写 —— 见 list_conversation_messages。"""
    page = paginate(_filtered(db, channel, kind, target_id, user_id, end_user, q, created_from, created_to).order_by(*_ORDER), params)
    page["items"] = _serialize(db, page["items"])
    return page


def list_conversation_messages(db: Session, conversation_id: int, user: User, full_tool_results: bool = False) -> list[dict]:
    """管理员查看任意会话的消息（只读）：会话不存在 404，不看归属。

    查看**他人**的会话属于敏感操作，写审计 view / conversation，detail 记会话归属人与通道，
    据此能追到"谁看过谁的会话"；看自己的会话不记（那是日常操作，记了只会淹没真正的查看记录）。
    审计在序列化之后：record_audit 自带 commit（见 core.audit 的说明），先序列化再记，
    避免出现"审计已落库、接口却 500"这种追不到结果的记录。
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise BizError(404, "会话不存在")
    rows = conversation_service.serialize_messages(db, conversation_id, full_tool_results)
    if conv.user_id != user.id:
        owner = db.get(User, conv.user_id)
        record_audit(db, user, "view", "conversation", conv.id, detail={
            "owner_user_id": conv.user_id, "owner_username": owner.username if owner else None,
            "channel": conv.channel, "kind": conv.kind, "target_id": _target_id(conv),
            "full_tool_results": full_tool_results,
        })
    return rows
