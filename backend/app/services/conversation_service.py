from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.limits import TOOL_RESULT_PREVIEW_CHARS, TOOL_RESULT_STORE_CHARS
from app.core.pagination import PageParams, paginate
from app.db.session import rows_to_dict
from app.db.models import Agent, ApiKey, Conversation, Message, ModelConfig, User, Workflow

# 三种对话类型（docs/17 §3.1）：模型对话、智能体对话、工作流对话。
# 定义放在会话模块：kind 是会话的列，归属判定、列表过滤、序列化都在这里，别处按 kind 分支时引用它。
KIND_MODEL = "model"
KIND_AGENT = "agent"
KIND_WORKFLOW = "workflow"
KINDS = (KIND_MODEL, KIND_AGENT, KIND_WORKFLOW)

# 类型 → 会话上记录归属的列名。互斥由 DB 约束兜底（models.Conversation 的 ck_conversations_kind）
TARGET_COLUMN = {KIND_MODEL: "model_id", KIND_AGENT: "agent_id", KIND_WORKFLOW: "workflow_id"}

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


def owned_conversations(db: Session, caller: Caller, kind: str | None = None, target_id: int | None = None, q: str | None = None):
    """属于该调用方的会话查询（按更新时间倒序，id 作副键），列表与分享访客的会话列表共用。

    kind 与 target_id 是对话分类型后的过滤口径（docs/17 §3.7）：对话页左侧只列"这一类对话、这一个对象"的会话。
    只给 kind 不给 target_id 时列该类型的全部会话（工作台"最近会话"用不到，但接口口径要完整）。
    """
    query = _owned_filter(db.query(Conversation), caller)
    if kind:
        query = query.filter(Conversation.kind == kind)
    if target_id:
        if kind is None:
            raise BizError(400, "按对象过滤会话时必须同时指定对话类型 kind")
        query = query.filter(getattr(Conversation, TARGET_COLUMN[kind]) == target_id)
    if q:
        query = query.filter(Conversation.title.ilike(f"%{q}%"))
    return query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())


def list_conversations(db: Session, caller: Caller, params: PageParams, kind: str | None = None, target_id: int | None = None,
                       q: str | None = None) -> dict:
    """分页列出属于该调用方的会话（登录：本人在界面里的；API Key：这个 Key 与同一个 end_user 建的），
    可按对话类型与对象过滤、按标题模糊搜索，按更新时间倒序（最近活跃在前）。
    附带消息数与对象名：消息数用一次分组查询，三种类型的名字各一次 IN 查询，不逐行查库。"""
    page = paginate(owned_conversations(db, caller, kind, target_id, q), params)
    page["items"] = _serialize(db, page["items"])
    return page


def get_conversation(db: Session, conversation_id: int, caller: Caller) -> dict:
    """单个会话，结构同列表项；不属于该调用方 404。对话页只带 conversation 深链时据此定位对话类型与对象。"""
    return _serialize(db, [get_owned_conversation(db, conversation_id, caller)])[0]


def _names_of(db: Session, rows: list[Conversation]) -> dict:
    """三种类型的对象名各批量查一次，返回 {(kind, id): 名字}。删掉对象后会话随外键级联消失，查不到即返回 None。"""
    ids_of = {kind: {getattr(c, column) for c in rows if c.kind == kind and getattr(c, column)} for kind, column in TARGET_COLUMN.items()}
    tables = {KIND_MODEL: ModelConfig, KIND_AGENT: Agent, KIND_WORKFLOW: Workflow}
    names: dict = {}
    for kind, table in tables.items():
        ids = ids_of[kind]
        if not ids:
            continue
        for row_id, name in db.query(table.id, table.name).filter(table.id.in_(ids)).all():
            names[(kind, row_id)] = name
    return names


def _serialize(db: Session, rows: list[Conversation]) -> list[dict]:
    """会话行 → 接口结构：消息数用一次分组查询，对象名按类型各一次 IN 查询，不逐行查库。

    kind / target_id / target_name 是三种对话统一的归属口径（docs/17 §3.3）：前端按 kind 切页签、
    按 target_id 选对象，不需要知道哪个类型对应哪一列。原来的 agent_id / agent_name 已随之退休。
    """
    ids = [c.id for c in rows]
    counts = rows_to_dict(db.query(Message.conversation_id, func.count(Message.id)).filter(Message.conversation_id.in_(ids)).group_by(Message.conversation_id).all()) if ids else {}
    names = _names_of(db, rows)
    return [{
        "id": c.id, "kind": c.kind, "target_id": getattr(c, TARGET_COLUMN[c.kind], None),
        "target_name": names.get((c.kind, getattr(c, TARGET_COLUMN[c.kind], None))),
        "title": c.title, "summary": c.summary,
        "message_count": int(counts.get(c.id, 0)),
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    } for c in rows]


def _tool_calls_for_display(tool_calls: list, full: bool) -> list:
    """工具调用记录按展示口径返回。库里的结果是按 STORE（8000）存的，历史接口默认只给 PREVIEW（200），
    与实时 tool_result 事件、前端工具卡片同长，避免会话页把整份工具结果都拉下来；超出的标 truncated 与截断前长度。
    full=True 时返回库里那份（≤ STORE），只给平台人员排查用。"""
    limit = TOOL_RESULT_STORE_CHARS if full else TOOL_RESULT_PREVIEW_CHARS
    rows = []
    for tc in tool_calls or []:
        item = dict(tc)
        result = item.get("result")
        if isinstance(result, str) and len(result) > limit:
            item["result"] = result[:limit]
            item["result_truncated"] = True
            item["result_chars"] = len(result)  # 截断前的长度（库里那份的长度，原始返回可能更长）
        rows.append(item)
    return rows


# 历史消息一次最多返回多少条。原来是"整段返回"，长会话（每条最多带 8000 字工具结果）
# 一次能返回几十 MB —— 页面会卡死，服务端也要把整份数据读进内存再序列化。
# 取最近 N 条而不是最早 N 条：打开会话要看的是最近的对话，往前翻是次要需求。
MESSAGES_MAX = 500


def list_messages(db: Session, conversation_id: int, caller: Caller, full_tool_results: bool = False,
                  full_allowed: bool = False, limit: int = MESSAGES_MAX) -> list[dict]:
    """取会话内最近 limit 条消息（按 ID 升序返回，即对话顺序），先校验会话归属。
    token_usage 随消息返回，刷新后历史消息仍能显示用量。
    工具结果按 PREVIEW 返回；full_tool_results 才给库里那份完整结果，full_allowed 由路由按调用方身份给出
    （admin / developer 的登录请求），先校验归属再判权限，不通过的不暴露会话是否存在。
    分享访客不走这里（会把工具入参与结果、引用的 kb_id / score、用量整包返回），用 share_service 的访客结构。

    **上限是必须的**：消息内容里带工具结果（每条最多 8000 字），无上限时打开一个长会话
    就是把几十 MB 拉进浏览器。取最近 N 条用"倒序取 N 再翻回来"，只扫索引不扫全表。"""
    get_owned_conversation(db, conversation_id, caller)
    if full_tool_results and not full_allowed:
        raise BizError(403, "只有 admin / developer 的登录请求可以查看完整工具结果")
    cap = max(1, min(limit, MESSAGES_MAX))
    rows = list(reversed(
        db.query(Message).filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc()).limit(cap).all()
    ))
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_calls": _tool_calls_for_display(m.tool_calls, full_tool_results),
            "citations": m.citations,
            "token_usage": m.token_usage or None,
            # 思维链全文随历史返回：刷新后"思考过程"折叠行才能回放（空串归 None，前端按有无内容决定渲染）
            "reasoning": m.reasoning or None,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


def delete_conversation(db: Session, conversation_id: int, caller: Caller) -> None:
    """删除会话（消息随外键 CASCADE 级联删除），先校验会话归属。"""
    conv = get_owned_conversation(db, conversation_id, caller)
    db.delete(conv)
    db.commit()
