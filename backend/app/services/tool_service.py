from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.security import encrypt_secret
from app.db.models import Agent, Tool, User
from app.tools.executor import execute_tool
from app.tools.schema import check_tool_args

SORTABLE = {"id": Tool.id, "name": Tool.name, "type": Tool.type, "timeout": Tool.timeout}
# 请求头键名含这些词就当作凭据（docs/15 RS-06）：凭据要走鉴权配置加密托管，不能放在会原样回传的 config.headers 里
SECRET_HEADER_MARKERS = ("authorization", "cookie", "token", "key", "secret")
# 进审计"改了哪些字段"的对比项；凭据单独记"已更换 / 已清除"，不进对比
_AUDITED_FIELDS = ("name", "description", "type", "config", "timeout", "auth")


def secret_header_keys(headers: dict | None) -> list[str]:
    return [k for k in (headers or {}) if any(m in str(k).lower() for m in SECRET_HEADER_MARKERS)]


def _auth_out(t: Tool) -> dict:
    """对外只给鉴权方式与位置和"是否已配置凭据"，凭据本身任何接口都不回传（2026-09-29 前请求头里的 Token 原样返回）。"""
    auth = t.auth or {}
    return {"type": auth.get("type") or "none", "location": auth.get("location"), "name": auth.get("name"), "has_secret": bool(t.secret_enc)}


def _to_dict(t: Tool, agents_count: int = 0, creator: str | None = None) -> dict:
    return {
        "id": t.id, "name": t.name, "description": t.description, "type": t.type,
        "config": t.config, "timeout": t.timeout, "is_enabled": t.is_enabled, "agents_count": agents_count,
        "auth": _auth_out(t), "created_by": t.created_by, "created_by_username": creator,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _creators(db: Session, tools: list) -> dict:
    ids = {t.created_by for t in tools if t.created_by}
    return dict(db.query(User.id, User.username).filter(User.id.in_(ids)).all()) if ids else {}


def _check_auth(data, has_secret_after: bool) -> None:
    """鉴权与凭据的组合校验（格式由 ToolIn 管）：内置工具不需要鉴权；选了鉴权方式就得有凭据；没选却填了凭据也拒绝，免得以为生效了。"""
    kind = data.auth.type
    if data.type == "builtin" and kind != "none":
        raise BizError(400, "内置工具不需要鉴权")
    if kind != "none" and not has_secret_after:
        raise BizError(400, f"鉴权方式为 {kind}，请填写凭据")
    if kind == "none" and data.secret:
        raise BizError(400, "没有选择鉴权方式，凭据不会被使用；请先选择鉴权方式")


def _agents_count_by_tool(db: Session, tool_ids: set[int]) -> dict[int, int]:
    """引用各工具的智能体数。tool_ids 是 JSONB 数组没有外键，一次拉回全部智能体的 (id, tool_ids) 在内存里数；
    智能体表小，避免对每个工具发一条 contains 查询。"""
    if not tool_ids:
        return {}
    counts = {tid: 0 for tid in tool_ids}
    for (ids,) in db.query(Agent.tool_ids).all():
        for tid in ids or []:
            if tid in counts:
                counts[tid] += 1
    return counts


def list_tools(db: Session, params: PageParams, q: str = None, tool_type: str = None, is_enabled: bool = None, sort: SortParams = None) -> dict:
    """分页列出工具：q 名称模糊，可按类型、启用状态过滤，白名单排序；附引用它的智能体数。"""
    query = db.query(Tool)
    if q:
        query = query.filter(Tool.name.ilike(f"%{q}%"))
    if tool_type:
        query = query.filter(Tool.type == tool_type)
    if is_enabled is not None:
        query = query.filter(Tool.is_enabled.is_(is_enabled))
    page = paginate(apply_sort(query, sort, SORTABLE, [Tool.id.asc()]), params)
    counts = _agents_count_by_tool(db, {t.id for t in page["items"]})
    creators = _creators(db, page["items"])
    page["items"] = [_to_dict(t, counts.get(t.id, 0), creators.get(t.created_by)) for t in page["items"]]
    return page


def create_tool(db: Session, data, user: User) -> dict:
    """新建工具（type 决定执行方式，config 为各类型工具的参数配置）。凭据加密后存 secret_enc；写审计 create。"""
    _check_auth(data, bool(data.secret))
    t = Tool(name=data.name, description=data.description, type=data.type, config=data.config, timeout=data.timeout,
             auth=data.auth.stored(), secret_enc=encrypt_secret(data.secret) if data.secret else None, created_by=user.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    record_audit(db, user, "create", "tool", t.id, detail={"name": t.name, "auth": _auth_out(t)["type"]})
    return _to_dict(t, creator=user.username)


def get_tool(db: Session, tool_id: int) -> Tool:
    """按 ID 取工具，不存在抛 BizError(404)。"""
    t = db.get(Tool, tool_id)
    if t is None:
        raise BizError(404, "工具不存在")
    return t


def get_tool_detail(db: Session, tool_id: int) -> dict:
    """工具详情：附引用它的智能体清单（id / name / status）。"""
    t = get_tool(db, tool_id)
    agents = [{"id": a.id, "name": a.name, "status": a.status} for a in db.query(Agent).filter(Agent.tool_ids.contains([tool_id])).order_by(Agent.id).all()]
    return {**_to_dict(t, len(agents), _creators(db, [t]).get(t.created_by)), "agents": agents}


def update_tool(db: Session, tool_id: int, data, user: User) -> dict:
    """覆盖式更新工具配置。凭据：secret 不传沿用、传了更换、clear_secret 清除；鉴权方式改成 none 时一并清除。
    写审计 update，detail 只记改了哪些字段，凭据只记"已更换 / 已清除"，不含明文。"""
    t = get_tool(db, tool_id)
    had_secret = bool(t.secret_enc)
    _check_auth(data, bool(data.secret) or (had_secret and not data.clear_secret))
    before = {f: getattr(t, f) for f in _AUDITED_FIELDS}
    t.name = data.name
    t.description = data.description
    t.type = data.type
    t.config = data.config
    t.timeout = data.timeout
    t.auth = data.auth.stored()
    secret_change = None
    if data.secret:
        t.secret_enc, secret_change = encrypt_secret(data.secret), "已更换"
    elif had_secret and (data.clear_secret or data.auth.type == "none"):
        t.secret_enc, secret_change = None, "已清除"
    changed = [f for f in _AUDITED_FIELDS if before[f] != getattr(t, f)]
    db.commit()
    db.refresh(t)
    if changed or secret_change:
        detail = {"name": t.name, "changed": changed, **({"secret": secret_change} if secret_change else {})}
        record_audit(db, user, "update", "tool", t.id, detail=detail)
    return _to_dict(t, creator=_creators(db, [t]).get(t.created_by))


def set_tool_enabled(db: Session, tool_id: int, enabled: bool, user: User) -> dict:
    """启用 / 停用工具（幂等，状态没变不写审计）。停用的工具仍保留在智能体的 tool_ids 里，只是不再暴露给模型（见 langchain_tools.build_tools）。"""
    t = get_tool(db, tool_id)
    if t.is_enabled != enabled:
        t.is_enabled = enabled
        db.commit()
        record_audit(db, user, "enable" if enabled else "disable", "tool", t.id, detail={"name": t.name})
    return {"id": t.id, "is_enabled": t.is_enabled}


def delete_tool(db: Session, tool_id: int, user: User) -> None:
    """删除工具。

    tools 与智能体的关联是 agents.tool_ids（JSONB 列表）而非外键，删除后不会级联清理，
    这里主动把该 tool_id 从所有智能体的 tool_ids 里移除，避免留下悬空引用
    （否则对话/工作流运行时会按已不存在的工具做无谓查询或报"工具不存在"）。
    """
    t = get_tool(db, tool_id)
    agents = db.query(Agent).filter(Agent.tool_ids.contains([tool_id])).all()
    for a in agents:
        if tool_id in a.tool_ids:
            a.tool_ids = [x for x in a.tool_ids if x != tool_id]
    name = t.name
    db.delete(t)
    db.commit()
    record_audit(db, user, "delete", "tool", tool_id, detail={"name": name, "detached_agents": len(agents)})


def apply_batch_action(db: Session, tool_id: int, action: str, user: User) -> None:
    """批量操作的单条执行（enable / disable / delete）。"""
    if action == "delete":
        delete_tool(db, tool_id, user)
    else:
        set_tool_enabled(db, tool_id, action == "enable", user)


async def test_tool(db: Session, tool_id: int, args: dict) -> dict:
    """用给定参数实际执行一次工具，供前端测试配置是否可用。HTTP 工具先按参数声明校验，不合法 400 且不发起调用。"""
    t = get_tool(db, tool_id)
    try:
        args = check_tool_args(t, args)
    except ValueError as e:
        raise BizError(400, str(e)) from e
    return await execute_tool(t, args)
