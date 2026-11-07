"""MCP 服务器服务（docs/17 §5，P5）：登记外部 MCP server、同步远端工具、删除与停用。

**落地形态**：MCP 工具就是 `tools` 表里的一行（`type='mcp'`），不另开执行路径。
理由（§5.2）：闸门（allowed_hosts）、审计、工作流工具节点、工具页测试、停用开关这五处
已经围着 `execute_tool` 建好了；另开一条路径等于把这五件事各写一遍，且迟早漏一处。

**同步语义**：
- 远端有、库里没有 → 新建一行，**默认停用**（§5 风险控制：远端工具描述是外部输入，先由人看过再启用）
- 远端有、库里也有 → 更新 name / description / config.parameters，**不动 is_enabled**
- 远端没有、库里有 → 标记 `is_enabled=false` + 写 last_error，**不物理删除**
  （删了会破坏已有智能体的 tool_ids 引用，那些智能体下次对话会查不到工具）
"""
from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import McpServer, Tool, User
from app.db.session import rows_to_dict
from app.mcp import client
from app.tools.schema import MAX_PROPERTIES, PROPERTY_NAME_RE, ToolParameters

logger = logging.getLogger(__name__)

SORTABLE = {"id": McpServer.id, "name": McpServer.name, "updated_at": McpServer.updated_at}
MAX_ALLOWED_HOSTS = 20
# 与 tools 同一套凭据判定：请求头里出现这些词就当凭据，必须在 secret 里配
SECRET_HEADER_MARKERS = ("authorization", "cookie", "token", "key", "secret")
# 同步出来的工具名上限（tools.name 是 varchar(128)）
TOOL_NAME_MAX = 128
# 远端工具描述进 tools.description，过长会撑爆提示词
DESCRIPTION_MAX = 1024


def secret_header_keys(headers: dict | None) -> list[str]:
    return [k for k in (headers or {}) if any(m in str(k).lower() for m in SECRET_HEADER_MARKERS)]


def _to_dict(s: McpServer, tools_count: int = 0, creator: str | None = None) -> dict:
    """对外形态：凭据只回 has_secret，明文任何接口都不出现（与 tools.auth 同一口径）。"""
    return {
        "id": s.id, "name": s.name, "description": s.description, "transport": s.transport,
        "url": s.url, "headers": s.headers or {}, "has_secret": bool(s.secret_enc),
        "is_enabled": s.is_enabled, "allowed_hosts": s.allowed_hosts or [],
        "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
        "last_error": s.last_error, "tools_count": tools_count,
        "created_by": s.created_by, "created_by_username": creator,
        "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat(),
    }


def _creators(db: Session, rows: list) -> dict:
    ids = {s.created_by for s in rows if s.created_by}
    return rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(ids)).all()) if ids else {}


def _tools_count(db: Session, server_ids: set[int]) -> dict[int, int]:
    """各服务器同步出的工具数。一次 group by 拿完，不逐行查库。"""
    if not server_ids:
        return {}
    rows = db.query(Tool.mcp_server_id, func.count(Tool.id)).filter(
        Tool.mcp_server_id.in_(server_ids)
    ).group_by(Tool.mcp_server_id).all()
    return {sid: n for sid, n in rows if sid is not None}


def get_server(db: Session, server_id: int) -> McpServer:
    s = db.get(McpServer, server_id)
    if s is None:
        raise BizError(404, "MCP 服务器不存在")
    return s


def list_servers(db: Session, params: PageParams, q: str | None = None, is_enabled: bool | None = None,
                 sort: SortParams | None = None) -> dict:
    """分页列出服务器：q 对 name / description 模糊匹配，附已同步工具数与创建人。"""
    query = db.query(McpServer)
    if q:
        query = query.filter(McpServer.name.ilike(f"%{q}%") | McpServer.description.ilike(f"%{q}%"))
    if is_enabled is not None:
        query = query.filter(McpServer.is_enabled.is_(is_enabled))
    page = paginate(apply_sort(query, sort, SORTABLE, [McpServer.id.asc()]), params)
    rows = page["items"]
    counts = _tools_count(db, {s.id for s in rows})
    creators = _creators(db, rows)
    page["items"] = [_to_dict(s, counts.get(s.id, 0), creators.get(s.created_by)) for s in rows]
    return page


def get_detail(db: Session, server_id: int) -> dict:
    """服务器详情：附它同步出来的工具清单（id / name / remote_name / is_enabled / 被几个智能体引用）。"""
    s = get_server(db, server_id)
    tools = db.query(Tool).filter(Tool.mcp_server_id == server_id).order_by(Tool.id).all()
    from app.services import tool_service  # 局部导入：tool_service 依赖 executor，避免循环

    counts = tool_service._agents_count_by_tool(db, {t.id for t in tools})
    return {
        **_to_dict(s, len(tools), _creators(db, [s]).get(s.created_by)),
        "tools": [
            {"id": t.id, "name": t.name, "remote_name": t.remote_name, "description": t.description,
             "is_enabled": t.is_enabled, "agents_count": counts.get(t.id, 0)}
            for t in tools
        ],
    }


def _check_url(url: str) -> None:
    """只允许 http / https。stdio 不支持，别的协议也不该出现在这里。"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BizError(400, "地址必须以 http:// 或 https:// 开头")
    if not parsed.hostname:
        raise BizError(400, "地址缺少主机名")


def _check_allowed_hosts(hosts: list | None) -> list[str]:
    """出站白名单：只写主机名，不带协议、端口与路径（与 tools 同一套判定）。

    与 HTTP 工具的区别：这里**不允许为空**。MCP 的地址由管理员配，没配白名单就无从
    判断目标是否可信；空名单等于这道闸门不存在（docs/16 P3a 的收口结论）。
    """
    if not hosts:
        raise BizError(400, "必须配置 allowed_hosts：MCP 服务器地址是外部输入，不填白名单无从判断目标是否可信")
    if not isinstance(hosts, list):
        raise BizError(400, "allowed_hosts 必须是数组")
    if len(hosts) > MAX_ALLOWED_HOSTS:
        raise BizError(400, f"allowed_hosts 最多 {MAX_ALLOWED_HOSTS} 项")
    out: list[str] = []
    for host in hosts:
        if not isinstance(host, str) or not host.strip():
            raise BizError(400, "allowed_hosts 里的每一项都必须是非空字符串")
        if "/" in host or ":" in host or len(host) > 255:
            raise BizError(400, f"allowed_hosts 里的 {host!r} 不是合法主机名（只写域名，不带协议、端口与路径）")
        out.append(host.strip().lower())
    return out


def _check_name_taken(db: Session, name: str, exclude_id: int | None = None) -> None:
    query = db.query(McpServer.id).filter(McpServer.name == name)
    if exclude_id is not None:
        query = query.filter(McpServer.id != exclude_id)
    if db.query(query.exists()).scalar():
        raise BizError(409, "服务器名称已存在")


def create_server(db: Session, data, user: User) -> dict:
    _check_url(data.url)
    allowed = _check_allowed_hosts(data.allowed_hosts)
    leaked = secret_header_keys(data.headers)
    if leaked:
        raise BizError(400, f"请在凭据里配置密钥，不要写进请求头：{', '.join(leaked)}")
    _check_name_taken(db, data.name)
    s = McpServer(
        name=data.name, description=data.description, transport=data.transport, url=data.url,
        headers=data.headers or {}, secret_enc=encrypt_secret(data.secret) if data.secret else None,
        is_enabled=data.is_enabled, allowed_hosts=allowed, created_by=user.id,
    )
    db.add(s)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BizError(409, "服务器名称已存在") from e
    db.refresh(s)
    record_audit(db, user, "create", "mcp_server", s.id, detail={"name": s.name, "url": s.url})
    return _to_dict(s, 0, user.username)


def update_server(db: Session, server_id: int, data, user: User) -> dict:
    """整体覆盖。凭据：secret 不传沿用、传了更换、clear_secret 清除（与工具同一口径）。"""
    s = get_server(db, server_id)
    _check_url(data.url)
    allowed = _check_allowed_hosts(data.allowed_hosts)
    leaked = secret_header_keys(data.headers)
    if leaked:
        raise BizError(400, f"请在凭据里配置密钥，不要写进请求头：{', '.join(leaked)}")
    _check_name_taken(db, data.name, exclude_id=server_id)

    before = {"name": s.name, "description": s.description, "transport": s.transport, "url": s.url,
              "headers": s.headers, "allowed_hosts": s.allowed_hosts, "is_enabled": s.is_enabled}
    s.name = data.name
    s.description = data.description
    s.transport = data.transport
    s.url = data.url
    s.headers = data.headers or {}
    s.allowed_hosts = allowed
    s.is_enabled = data.is_enabled
    secret_change = None
    if data.secret:
        s.secret_enc, secret_change = encrypt_secret(data.secret), "已更换"
    elif data.clear_secret and s.secret_enc:
        s.secret_enc, secret_change = None, "已清除"
    changed = [k for k, v in before.items() if v != getattr(s, k)]
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BizError(409, "服务器名称已存在") from e
    db.refresh(s)
    if changed or secret_change:
        detail = {"name": s.name, "changed": changed, **({"secret": secret_change} if secret_change else {})}
        record_audit(db, user, "update", "mcp_server", s.id, detail=detail)
    return _to_dict(s, _tools_count(db, {s.id}).get(s.id, 0), _creators(db, [s]).get(s.created_by))


def set_enabled(db: Session, server_id: int, enabled: bool, user: User) -> dict:
    """启用 / 停用服务器。

    停用服务器同时停用它同步出来的工具：服务器都关了，它的工具还能被模型调用是说不通的
    （地址、凭据都在服务器那一行上，停用即失效）。启用服务器**不**自动启用工具 ——
    远端工具的启用是逐个人工确认的动作（§5 风险控制），这里不替人做决定。
    """
    s = get_server(db, server_id)
    if s.is_enabled != enabled:
        s.is_enabled = enabled
        if not enabled:
            for t in db.query(Tool).filter(Tool.mcp_server_id == server_id, Tool.is_enabled.is_(True)).all():
                t.is_enabled = False
        db.commit()
        record_audit(db, user, "enable" if enabled else "disable", "mcp_server", s.id, detail={"name": s.name})
    return {"id": s.id, "is_enabled": s.is_enabled}


def delete_server(db: Session, server_id: int, user: User) -> None:
    """删除服务器。同步出来的工具**保留但全部停用**，不物理删除。

    删工具会破坏已有智能体的 tool_ids 引用（与 tool_service.delete_tool 主动摘引用的处理不同：
    这里的工具是同步产物，智能体绑的是"这一行的 id"，删掉后引用变成悬空 id，装配时查不到；
    停用则语义清楚——模型看不到它，工具页还能看到"来源服务器已删除"）。
    """
    s = get_server(db, server_id)
    tools = db.query(Tool).filter(Tool.mcp_server_id == server_id).all()
    for t in tools:
        t.is_enabled = False
        t.config = {**(t.config or {}), "source_deleted": True}
    name = s.name
    db.delete(s)
    db.commit()
    record_audit(db, user, "delete", "mcp_server", server_id,
                 detail={"name": name, "disabled_tools": len(tools)})


def _to_tool_parameters(schema: dict) -> tuple[dict, list[str], list[str]]:
    """把远端 inputSchema 转成本项目的 JSON Schema 子集（tools/schema.ToolParameters）。

    本项目的声明只支持标量、无嵌套（docs/15 FR-030 的既有约束），而 MCP 的 inputSchema
    是完整的 JSON Schema。转换规则：
    - 顶层 object 的 properties 逐个看：string / number / integer / boolean 直接映射
    - enum 只保留字符串枚举（本项目的 enum 只对 string 有意义）
    - 数组、对象、oneOf 等 → 降级为 string 类型并保留原描述，调用前再按 JSON 解析回去
      降级是必要的：不支持就丢参数，模型会漏传必填项，调用必然失败
    - required 里只保留真正转出来的那些

    返回 (声明, 降级说明, 被降级的参数名)。后两者写进 tools.config.schema_notes / degraded_params：
    说明供工具页标黄提示，参数名列表供 build_call_args 在转发前把文本解析回对象 / 数组。
    """
    notes: list[str] = []
    degraded: list[str] = []
    props_in = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props_in, dict):
        return {"type": "object", "properties": {}, "required": []}, notes, degraded

    properties: dict[str, dict] = {}
    for name, raw in props_in.items():
        if len(properties) >= MAX_PROPERTIES:
            notes.append(f"参数超过 {MAX_PROPERTIES} 个，多余的已忽略")
            break
        if not PROPERTY_NAME_RE.match(str(name)):
            notes.append(f"参数名 {name!r} 不合法（需匹配 ^[A-Za-z_][A-Za-z0-9_]*$），已忽略")
            continue
        if not isinstance(raw, dict):
            continue
        kind = raw.get("type")
        description = str(raw.get("description") or "")
        if kind in ("string", "number", "integer", "boolean"):
            prop: dict = {"type": kind, "description": description}
            enum = raw.get("enum")
            if kind == "string" and isinstance(enum, list) and enum and all(isinstance(x, str) for x in enum):
                prop["enum"] = enum
            properties[str(name)] = prop
        else:
            # 嵌套对象 / 数组 / oneOf：降级为自由文本，保留原描述让模型知道该传什么。
            # 记进 degraded：调用前要按 JSON 解析回去，否则远端收到的是字符串而不是数组/对象。
            properties[str(name)] = {
                "type": "string",
                "description": (description + "（复杂结构，请传 JSON 字符串）").strip(),
            }
            degraded.append(str(name))
            notes.append(f"参数 {name} 的类型 {kind or '未声明'} 超出支持范围，已降级为文本（调用时按 JSON 解析）")

    required_in = schema.get("required")
    required = [str(r) for r in required_in if isinstance(required_in, list) and str(r) in properties] \
        if isinstance(required_in, list) else []
    return {"type": "object", "properties": properties, "required": required}, notes, degraded


def _tool_name(server_name: str, remote_name: str) -> str:
    """本地工具名：`{server}_{remote}`，避免跨 server 重名（§5.2）。

    清洗成 `[A-Za-z0-9_-]`：工具名会出现在模型生成的 tool_calls 里，点、斜杠、空格这类字符
    会让部分模型不肯调用。**连字符要保留** —— 它被模型 API 明确允许（OpenAI 的函数名规则是
    `^[a-zA-Z0-9_-]+$`），而且清洗掉会让名字变难读，也会把 `pytest-` 这类前缀打成
    `pytest_`，测试回收的按前缀匹配就再也找不到它们（2026-11-07 漏出 10 个孤儿工具）。
    超长时截断，保证不超过 tools.name 的 128 字符。
    """
    import re

    def clean(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", s)

    head = clean(server_name)[:40]
    tail = clean(remote_name)[: TOOL_NAME_MAX - len(head) - 1]
    return f"{head}_{tail}"[:TOOL_NAME_MAX]


async def sync_tools(db: Session, server_id: int, user: User) -> dict:
    """连一次远端、拉工具清单、按 §5.2 的规则 upsert。

    远端不可达时**不抛 500**：写 last_error 并返回同步结果（created=0 等），
    让页面能显示"上次同步失败：xxx"。抛 500 的话前端只能看到一个红 toast，看不到原因。
    """
    s = get_server(db, server_id)
    if not s.is_enabled:
        raise BizError(400, "服务器已停用，请先启用再同步")

    secret = decrypt_secret(s.secret_enc) if s.secret_enc else None
    try:
        remote_tools = await client.probe(s.url, s.transport, s.headers or {}, secret, float(30))
    except client.McpError as e:
        s.last_error = str(e)
        db.commit()
        logger.warning("MCP 同步失败 server=%s url=%s error=%s", s.name, s.url, e)
        raise BizError(502, f"同步失败：{e}") from e

    existing = {t.remote_name: t for t in db.query(Tool).filter(Tool.mcp_server_id == server_id).all()}
    created, updated, disabled = 0, 0, 0
    seen: set[str] = set()

    for rt in remote_tools:
        seen.add(rt.name)
        parameters, notes, degraded = _to_tool_parameters(rt.input_schema)
        config = {
            "parameters": parameters,
            "schema_notes": notes,
            # 被降级的参数名：build_call_args 转发前按 JSON 解析回对象 / 数组
            "degraded_params": degraded,
            # 出站白名单跟着服务器走：工具的判定读的是它自己 config 里的这一份
            "allowed_hosts": list(s.allowed_hosts or []),
            "url": s.url,
        }
        description = (rt.description or f"来自 MCP 服务器 {s.name} 的工具 {rt.name}")[:DESCRIPTION_MAX]
        row = existing.get(rt.name)
        if row is None:
            db.add(Tool(
                name=_tool_name(s.name, rt.name), description=description, type="mcp",
                config=config, timeout=30,
                # 新建默认停用：远端工具描述是外部输入，先由人看过再启用（§5 风险控制）
                is_enabled=False, mcp_server_id=server_id, remote_name=rt.name, created_by=user.id,
            ))
            created += 1
        else:
            row.name = _tool_name(s.name, rt.name)
            row.description = description
            row.config = config
            # is_enabled 不动：那是人做的决定，同步不该替他改
            updated += 1

    for remote_name, row in existing.items():
        if remote_name not in seen:
            # 远端已经没有这个工具了：打标记让人在工具页看得见"来源已消失"。
            # 标记无条件写（本来就停用的也要标），否则页面无从区分"人手工停用"和"远端删了"。
            # disabled 只统计真正发生了状态变化的那些，用来告诉用户"这次同步停用了几个"。
            row.config = {**(row.config or {}), "source_missing": True}
            if row.is_enabled:
                row.is_enabled = False
                disabled += 1

    s.last_synced_at = func.now()
    s.last_error = None
    db.commit()
    record_audit(db, user, "update", "mcp_server", s.id,
                 detail={"name": s.name, "action": "sync", "created": created,
                         "updated": updated, "disabled": disabled})
    return {"created": created, "updated": updated, "disabled": disabled, "total": len(remote_tools)}


async def test_connection(db: Session, data) -> dict:
    """测试连接（不落库）：连一次、取工具清单、返回条数与名字。

    用请求体里的配置而不是库里的行，这样新建时还没保存也能测。
    凭据：给了 secret 用它，没给则沿用 server_id 对应的已存凭据（编辑时不用重填）。
    """
    _check_url(data.url)
    _check_allowed_hosts(data.allowed_hosts)
    secret = data.secret
    if not secret and getattr(data, "server_id", None):
        existing = db.get(McpServer, data.server_id)
        if existing is not None and existing.secret_enc:
            secret = decrypt_secret(existing.secret_enc)
    try:
        tools = await client.probe(data.url, data.transport, data.headers or {}, secret, float(30))
    except client.McpError as e:
        raise BizError(502, f"连接失败：{e}") from e
    return {"ok": True, "count": len(tools), "tools": [t.name for t in tools]}


def build_call_args(tool: Tool, arguments: dict) -> dict:
    """调用前按声明校验参数，并把被降级的参数解析回对象 / 数组。

    MCP 工具的 config.parameters 是同步时从远端 inputSchema 转来的，走的是同一套
    ToolParameters 子集，因此可以直接复用 validate_args。

    降级还原这一步不能省：嵌套对象与数组在本项目的声明里只能写成 string（标量限制），
    但远端的 inputSchema 要的是真数组 / 真对象。只校验不还原的话，模型传
    `["a","b"]` 会被校验拒掉；传 `'["a","b"]'` 通过了校验，远端收到的却是个字符串，
    调用必然失败 —— 而且失败信息来自远端，看不出是这边的转换问题。
    """
    raw = (tool.config or {}).get("parameters")
    if raw is None:
        return arguments or {}
    try:
        parameters = ToolParameters.model_validate(raw)
    except Exception:
        logger.warning("MCP 工具 %s 的参数声明不合法，按原样转发", tool.name, exc_info=True)
        return arguments or {}
    from app.tools.schema import validate_args

    normalized, error = validate_args(parameters, arguments)
    if error:
        raise ValueError(f"参数校验失败：{error}")
    return _restore_degraded(tool, normalized)


def _restore_degraded(tool: Tool, args: dict) -> dict:
    """把降级成字符串的参数按 JSON 解析回原结构。解析失败保留原样并记日志（让远端去判错）。"""
    import json

    degraded = [n for n in ((tool.config or {}).get("degraded_params") or []) if n in args]
    if not degraded:
        return args
    out = dict(args)
    for name in degraded:
        value = out[name]
        if not isinstance(value, str):
            continue
        try:
            out[name] = json.loads(value)
        except json.JSONDecodeError:
            # 不是 JSON 就原样发：远端可能本来就要一个普通字符串
            logger.info("MCP 工具 %s 的参数 %s 不是合法 JSON，按原样转发", tool.name, name)
    return out
