import hashlib
import ipaddress
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core import rate_limiter
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.rate_limiter import RateLimitResult
from app.core.request_context import get_client_ip
from app.db.session import rows_to_dict
from app.db.models import Agent, ApiKey, KnowledgeBase, User, Workflow
from app.services import kb_service


logger = logging.getLogger(__name__)


def hash_key(key: str) -> str:
    """对明文 Key 做 SHA-256 单向哈希：库中只存哈希，明文无法还原。"""
    return hashlib.sha256(key.encode()).hexdigest()


def _audit_rejected(db: Session, ak: ApiKey, action: str, reason: str, owner: User | None = None) -> None:
    """Key 被拒时留痕（docs/15 PB-11）：记到 Key 归属账号名下，detail 只放 Key id 与前缀、原因，绝不含明文或哈希。
    不存在"行"的拒绝（Key 压根查不到）没有归属可写，由调用方记结构化日志。
    owner 已拿到时传进来，省掉一次按 user_id 的查询（被拒路径也可能有高频调用）。
    """
    if owner is None:
        owner = db.get(User, ak.user_id)
    record_audit(db, owner, action, "api_key", ak.id,
                 detail={"reason": reason, "key_prefix": ak.key_prefix, "owner_user_id": ak.user_id,
                         "expires_at": ak.expires_at.isoformat() if ak.expires_at else None})


def _ip_allowed(ip: str | None, allowed_ips: list) -> bool:
    """来源是否在白名单内。白名单为空不限制；有白名单但来源缺失或不是合法 IP 时按不允许（判不出来源宁可拒绝）。"""
    if not allowed_ips:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(item, strict=False) for item in allowed_ips)


def is_expired(k: ApiKey, now: datetime | None = None) -> bool:
    """Key 是否已过期（expires_at 为空 = 永不过期）。判定只在服务端做一次，前端拿到的 is_expired 是同一个口径。"""
    return k.expires_at is not None and k.expires_at <= (now or datetime.now(timezone.utc))


def authenticate(db: Session, raw_key: str) -> tuple[User, ApiKey, RateLimitResult]:
    """用明文 Key 鉴权并扣减一次配额，返回 (归属用户, Key, 限流结果)。

    判定顺序：Key 有效 → 未过期 → 归属账号可用 → 来源 IP 白名单 → 限流 → 扣配额。
    白名单与限流放在扣配额之前：被拒绝、被限流的请求不消耗配额。
    扣配额用带前置条件的 UPDATE（quota 为空表示不限，否则 used < quota）并按影响行数判断，并发请求下不会超扣。
    """
    ak = db.query(ApiKey).filter(ApiKey.key_hash == hash_key(raw_key)).first()
    if ak is None or not ak.is_enabled:
        # 不存在的 Key 没有行可归属，只留结构化日志（不带任何密钥片段）；停用的 Key 能定位到 id，写审计
        if ak is not None:
            _audit_rejected(db, ak, "api_key_disabled", "API Key 已停用")
        else:
            logger.warning("API Key 鉴权被拒：原因=不存在")
        raise BizError(401, "API Key 无效或已停用")
    if is_expired(ak):
        # 过期判定在服务端（docs/15 PB-11）：文案要与"已停用/已删除"一样明确，调用方才知道该换新 Key；
        # 放在扣配额之前 —— 过期的 Key 不该消耗任何额度
        _audit_rejected(db, ak, "api_key_expired", "API Key 已过期")
        raise BizError(401, "API Key 已过期")
    user = db.get(User, ak.user_id)
    if user is None or not user.is_active:
        # 归属账号停用是 403 而不是 401（Key 本身没错，是账号不能用了）；同样留痕，便于事后回答"谁在什么时候被拒"
        _audit_rejected(db, ak, "api_key_owner_inactive", "API Key 归属账号不可用", owner=user)
        raise BizError(403, "API Key 归属账号不可用")

    client_ip = get_client_ip()
    if not _ip_allowed(client_ip, ak.allowed_ips or []):
        # 记到 Key 归属账号名下：审计要能按 Key 追溯"谁的 Key 被什么来源拿去调了"
        record_audit(db, user, "api_key_ip_rejected", "api_key", ak.id, detail={"ip": client_ip, "key_prefix": ak.key_prefix})
        raise BizError(403, "API Key 不允许从该 IP 调用")

    limit = ak.rate_limit_per_minute or settings.RATE_LIMIT_API_KEY_PER_MINUTE
    rate_limit = rate_limiter.check("ak", str(ak.id), limit)
    if not rate_limit.allowed:
        raise rate_limiter.limit_exceeded(rate_limit)

    # quota 为空 = 不限次数（docs/15 PB-11）：此前 0 被页面当成"不限"，而 used < quota 让 0 变成"一次都调不了"
    consumed = (
        db.query(ApiKey)
        .filter(ApiKey.id == ak.id, or_(ApiKey.quota.is_(None), ApiKey.used < ApiKey.quota))
        .update({ApiKey.used: ApiKey.used + 1, ApiKey.last_used_at: datetime.now(timezone.utc)}, synchronize_session=False)
    )
    db.commit()
    if not consumed:
        raise BizError(429, "API Key 配额已用尽")
    # commit 之后 user 与 ak 都已过期（SessionLocal 是默认 expire_on_commit=True），
    # 再访问 user.role / ak.quota 会各自触发一次 SELECT —— 等于每个 Key 请求多两次查询。
    # 显式 refresh 一次把两者拉回来，比让调用方在后面陆续触发更省，也避免它在不同 session 里
    # 拿到半失效的对象。refresh 失败不该让请求失败：数据已经落库，配额确实扣了。
    try:
        db.refresh(user)
        db.refresh(ak)
    except Exception:
        logger.warning("API Key 鉴权后刷新对象失败，调用方可能多几次查询 id=%s", ak.id, exc_info=True)
    return user, ak, rate_limit


SORTABLE = {"id": ApiKey.id, "name": ApiKey.name, "used": ApiKey.used, "last_used_at": ApiKey.last_used_at, "created_at": ApiKey.created_at}
SCOPE_FIELDS = ("agent_ids", "workflow_ids", "kb_ids")


# ---------- 资源作用域（docs/15 3.7.1，D-09）：Key 只能调授权范围内的资源，没有"空 = 全部放行"的兜底 ----------

def check_agent_scope(api_key: ApiKey | None, agent_id: int) -> None:
    """Key 请求只能调作用域内的智能体（403）；JWT 请求（api_key 为 None）不受限。

    越权被拒也留痕（docs/15 PB-11）：这里只有 Key 行、没有 Session，写审计要另开会话且会污染调用方事务，
    所以记结构化日志（带 key id 与资源 id，不带任何密钥片段）。配额/停用/过期那几条在 authenticate 里写审计。
    """
    if api_key is not None and agent_id not in (api_key.agent_ids or []):
        logger.warning("API Key 越权被拒：key_id=%s agent_id=%s 原因=不在智能体作用域内", api_key.id, agent_id)
        raise BizError(403, "该 API Key 无权调用此智能体")


def check_workflow_scope(api_key: ApiKey | None, workflow_id: int) -> None:
    """Key 请求只能运行、续跑作用域内的工作流（403）；JWT 请求不受限。留痕口径同 check_agent_scope。"""
    if api_key is not None and workflow_id not in (api_key.workflow_ids or []):
        logger.warning("API Key 越权被拒：key_id=%s workflow_id=%s 原因=不在工作流作用域内", api_key.id, workflow_id)
        raise BizError(403, "该 API Key 无权调用此工作流")


def _check_scope(db: Session, agent_ids: list, workflow_ids: list, kb_ids: list, owner: User) -> None:
    """保存前校验作用域：三类至少一个非空（400）；引用的智能体、工作流须存在，知识库须存在且对归属人可见（KB-01），
    缺的一次列全（400）。不可见与不存在同一句提示，不暴露受限库是否存在。"""
    if not (agent_ids or workflow_ids or kb_ids):
        raise BizError(400, "至少授权一个智能体、工作流或知识库：API Key 只能调用授权范围内的资源")
    for model, ids, label, extra in ((Agent, agent_ids, "智能体", None), (Workflow, workflow_ids, "工作流", None),
                                     (KnowledgeBase, kb_ids, "知识库", kb_service.visible_kb_filter(owner.role))):
        if not ids:
            continue
        query = db.query(model.id).filter(model.id.in_(ids))
        found = {i for (i,) in (query.filter(extra) if extra is not None else query)}
        missing = [i for i in ids if i not in found]
        if missing:
            raise BizError(400, f"{label}不存在：{', '.join(str(i) for i in missing)}")


def _scope_names(db: Session, keys: list[ApiKey]) -> dict[str, dict[int, str]]:
    """一页 Key 的作用域里各资源的名称：三类各一次 IN 查询。查不到的（已删除）不在结果里，序列化时名称记 None。"""
    names: dict[str, dict[int, str]] = {}
    for field, model in (("agent_ids", Agent), ("workflow_ids", Workflow), ("kb_ids", KnowledgeBase)):
        ids = {i for k in keys for i in (getattr(k, field) or [])}
        names[field] = rows_to_dict(db.query(model.id, model.name).filter(model.id.in_(ids)).all()) if ids else {}
    return names


def _to_dict(k: ApiKey, username: str | None = None, names: dict | None = None) -> dict:
    """Key 元信息（只含前缀，永不返回明文与哈希）；username 是创建人，admin 视角区分归属。
    作用域给原始 ID（编辑表单回填）与带名称的清单 scope（列表与抽屉展示；资源已删除时 name 为 None）。
    expires_at 为空 = 永不过期；is_expired 由服务端按同一口径算好（前端只展示，不自己判）。"""
    names = names or {}
    scope = {field: [{"id": i, "name": names.get(field, {}).get(i)} for i in (getattr(k, field) or [])] for field in SCOPE_FIELDS}
    return {
        "id": k.id, "name": k.name, "key_prefix": k.key_prefix, "quota": k.quota, "used": k.used,
        "is_enabled": k.is_enabled, "allowed_ips": k.allowed_ips or [], "rate_limit_per_minute": k.rate_limit_per_minute,
        "agent_ids": list(k.agent_ids or []), "workflow_ids": list(k.workflow_ids or []), "kb_ids": list(k.kb_ids or []),
        "scope": {"agents": scope["agent_ids"], "workflows": scope["workflow_ids"], "knowledge_bases": scope["kb_ids"]},
        "user_id": k.user_id, "username": username,
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "is_expired": is_expired(k),
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


def _get_owned(db: Session, key_id: int, user: User) -> ApiKey:
    """按 id 取 Key。developer 只能取到本人创建的，他人的一律 404（不暴露存在性）；admin 不受限。"""
    k = db.get(ApiKey, key_id)
    if k is None or (user.role != "admin" and k.user_id != user.id):
        raise BizError(404, "API Key 不存在")
    return k


def list_api_keys(db: Session, params: PageParams, user: User, q: str | None = None, is_enabled: bool | None = None,
                  owner_id: int | None = None, sort: SortParams | None = None, agent_id: int | None = None, workflow_id: int | None = None, kb_id: int | None = None) -> dict:
    """分页列出 Key 元信息：admin 看全部（可按创建人过滤），developer 只看本人创建的；名称模糊、启用状态过滤，白名单排序。
    agent_id / workflow_id / kb_id 只取作用域含该资源的 Key（智能体"发布渠道"的密钥区用，docs/15 3.7.2）。
    创建人用户名一次 IN 查询装配。"""
    query = db.query(ApiKey)
    if user.role != "admin":
        query = query.filter(ApiKey.user_id == user.id)
    elif owner_id:
        query = query.filter(ApiKey.user_id == owner_id)
    for column, resource_id in ((ApiKey.agent_ids, agent_id), (ApiKey.workflow_ids, workflow_id), (ApiKey.kb_ids, kb_id)):
        if resource_id is not None:
            query = query.filter(column.contains([resource_id]))
    if q:
        query = query.filter(ApiKey.name.ilike(f"%{q}%"))
    if is_enabled is not None:
        query = query.filter(ApiKey.is_enabled.is_(is_enabled))
    page = paginate(apply_sort(query, sort, SORTABLE, [ApiKey.id.desc()]), params)
    user_ids = {k.user_id for k in page["items"]}
    names = rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()) if user_ids else {}
    scope_names = _scope_names(db, page["items"])
    page["items"] = [_to_dict(k, names.get(k.user_id), scope_names) for k in page["items"]]
    return page


def list_my_api_keys(db: Session, user: User, params: PageParams) -> dict:
    """归属本人的 Key（个人中心"我的 API 密钥"，docs/15 OP-03）：任何角色都能看，结构同管理列表，按 id 倒序分页。
    调用者看到的是管理员代发给自己的（D-15），只读——启停与删除仍只对 admin / developer 开放。"""
    page = paginate(db.query(ApiKey).filter(ApiKey.user_id == user.id).order_by(ApiKey.id.desc()), params)
    scope_names = _scope_names(db, page["items"])
    page["items"] = [_to_dict(k, user.username, scope_names) for k in page["items"]]
    return page


def _owner_for(db: Session, owner_user_id: int | None, user: User) -> User:
    """新 Key 的归属人：默认是创建人；admin 可以代发给别人（docs/15 D-15，调用者拿到的 Key 由管理员发放），
    其他角色指定别人 403；被代发的用户须存在且启用（400）。"""
    if owner_user_id is None or owner_user_id == user.id:
        return user
    if user.role != "admin":
        raise BizError(403, "只有管理员能替其他用户生成 API Key")
    owner = db.get(User, owner_user_id)
    if owner is None or not owner.is_active:
        raise BizError(400, "归属用户不存在或已停用")
    return owner


def set_api_key_enabled(db: Session, key_id: int, enabled: bool, user: User) -> dict:
    """设置启用状态（批量启停用；toggle 也走这里），幂等。写审计 enable / disable（detail 只含前缀）。"""
    k = _get_owned(db, key_id, user)
    k.is_enabled = enabled
    # commit / record_audit 都会 commit，之后对象过期、再读属性会各触发一次 SELECT：要用的值提前取出来
    key_id_, detail = k.id, {"name": k.name, "key_prefix": k.key_prefix}
    db.commit()
    record_audit(db, user, "enable" if enabled else "disable", "api_key", key_id_, detail=detail)
    return {"id": key_id_, "is_enabled": enabled}


def apply_batch_action(db: Session, key_id: int, action: str, user: User) -> None:
    """批量操作的单条执行（enable / disable / delete），归属校验与单条接口相同。"""
    if action == "delete":
        delete_api_key(db, key_id, user)
    else:
        set_api_key_enabled(db, key_id, action == "enable", user)


def create_api_key(db: Session, data, user: User) -> dict:
    """生成新 Key：明文只在此次响应返回一次，之后无法找回（落库仅存哈希与前缀）。
    归属人默认是当前用户，admin 可用 owner_user_id 代发（_owner_for）；作用域按归属人校验（_check_scope，知识库按归属人的角色判可见）。
    expires_at 为空 = 永不过期（docs/15 PB-11）；是否在未来由路由的 schema 校验（422），服务层不重复判。
    写审计 create / api_key（名称、前缀与归属人，2026-10-05 起；代发是替别人造凭据，要能追溯）。"""
    owner = _owner_for(db, data.owner_user_id, user)
    _check_scope(db, data.agent_ids, data.workflow_ids, data.kb_ids, owner)
    raw = "ak_" + secrets.token_hex(16)
    ak = ApiKey(
        user_id=owner.id,
        name=data.name,
        key_prefix=raw[:12] + "...",
        key_hash=hash_key(raw),
        quota=data.quota,
        allowed_ips=data.allowed_ips,
        rate_limit_per_minute=data.rate_limit_per_minute,
        agent_ids=data.agent_ids,
        workflow_ids=data.workflow_ids,
        kb_ids=data.kb_ids,
        expires_at=data.expires_at,
    )
    db.add(ak)
    db.commit()
    db.refresh(ak)
    record_audit(db, user, "create", "api_key", ak.id,
                 detail={"name": ak.name, "key_prefix": ak.key_prefix, "owner_user_id": owner.id,
                         "expires_at": ak.expires_at.isoformat() if ak.expires_at else None})
    return {**_to_dict(ak, owner.username, _scope_names(db, [ak])), "key": raw}


def update_api_key(db: Session, key_id: int, data, user: User) -> dict:
    """只更新请求里传了的字段（未传 = 不改；quota / expires_at 例外，显式 null 是有效值）；归属校验见 _get_owned。
    改了任一作用域时，按改后的三类整体再校验一次（至少一个非空；知识库按归属人的角色判可见，admin 代改他人 Key 时也一样）。
    expires_at 用 model_fields_set 区分"没传"与"显式传 null"（null = 清除有效期，永不过期）—— 不能用 None 判"未提供"。
    quota 同理：显式传 null = 改为不限次数。写审计 update / api_key，detail 只记改了哪些字段与 Key 前缀。"""
    k = _get_owned(db, key_id, user)
    if any(getattr(data, f) is not None for f in SCOPE_FIELDS):
        merged = {f: getattr(data, f) if getattr(data, f) is not None else list(getattr(k, f) or []) for f in SCOPE_FIELDS}
        owner = user if k.user_id == user.id else db.get(User, k.user_id)
        if owner is None:  # 归属用户已不存在；下面按它的角色判知识库可见性，没有角色可判
            raise BizError(400, "Key 的归属用户已不存在")
        _check_scope(db, merged["agent_ids"], merged["workflow_ids"], merged["kb_ids"], owner)
    changed: list[str] = []
    for field in ("name", "allowed_ips", "rate_limit_per_minute", *SCOPE_FIELDS):
        value = getattr(data, field)
        if value is not None:
            setattr(k, field, value)
            changed.append(field)
    # 可空字段（quota / expires_at）：只有请求里真的带了才动，显式 null 表示"改为不限次数" / "永不过期"。
    # 用 model_fields_set 而不是 "is not None"：这两个字段的 null 是有意义的值，不是"未提供"。
    for field in ("quota", "expires_at"):
        if field in data.model_fields_set:
            setattr(k, field, getattr(data, field))
            changed.append(field)
    db.commit()
    db.refresh(k)
    record_audit(db, user, "update", "api_key", k.id,
                 detail={"name": k.name, "key_prefix": k.key_prefix, "changed": sorted(set(changed)),
                         "expires_at": k.expires_at.isoformat() if k.expires_at else None})
    return _to_dict(k, None, _scope_names(db, [k]))


def rotate_api_key(db: Session, key_id: int, user: User) -> dict:
    """轮换密钥（docs/15 PB-11）：换一把新明文，其余设置（名称、配额、作用域、白名单、限速、有效期）原样保留。

    旧 Key 的语义：**原行换新明文，旧明文立即失效**（原地轮换，不新建行、不保留"旧 Key 并行可用"的过渡期）。
    理由（读代码后确定）：
    - 泄漏处置的诉求是"尽快让旧明文失效、调用方继续用同一个 Key 配置"，新行方案要么留下一条仍在生效的旧行
      （必须同时停用，那与原地轮换等价、只是多一行垃圾），要么删旧行（历史 runs.api_key_id / conversations.api_key_id
      会被 ON DELETE SET NULL 抹掉，用量与审计的追溯断掉）；
    - used 与 created_at 是"这把 Key 的累计用量"，轮换不改身份就该保留，否则配额被重置、用量页对不上；
    - 需要"新旧并行、平滑切换"的调用方可以再建一把 Key，那是另一种诉求（多把 Key），不该塞进 rotate 的语义里。
    审计 rotate / api_key，detail 只含前缀（明文与哈希绝不进审计，docs/06 第 10 节）。
    """
    k = _get_owned(db, key_id, user)
    raw = "ak_" + secrets.token_hex(16)
    old_prefix = k.key_prefix
    k.key_prefix = raw[:12] + "..."
    k.key_hash = hash_key(raw)
    db.commit()
    db.refresh(k)
    record_audit(db, user, "rotate", "api_key", k.id,
                 detail={"name": k.name, "key_prefix": k.key_prefix, "old_key_prefix": old_prefix})
    return {**_to_dict(k, None, _scope_names(db, [k])), "key": raw}


def toggle_api_key(db: Session, key_id: int, user: User) -> dict:
    """启用/停用某个 Key（停用后 authenticate 会直接拒绝）。写审计 enable / disable，detail 只含前缀。"""
    k = _get_owned(db, key_id, user)
    k.is_enabled = not k.is_enabled
    enabled = k.is_enabled
    key_id_, detail = k.id, {"name": k.name, "key_prefix": k.key_prefix}
    db.commit()
    record_audit(db, user, "enable" if enabled else "disable", "api_key", key_id_, detail=detail)
    return {"id": key_id_, "is_enabled": enabled}


def delete_api_key(db: Session, key_id: int, user: User) -> None:
    """删除 Key（立即失效），不存在或不属于本人抛 BizError(404)。写审计 delete（先序列化再删：
    record_audit 自带 commit，删完再读 k 的属性会因对象过期多一次查询）。"""
    k = _get_owned(db, key_id, user)
    detail = {"name": k.name, "key_prefix": k.key_prefix, "owner_user_id": k.user_id}
    db.delete(k)
    db.commit()
    record_audit(db, user, "delete", "api_key", key_id, detail=detail)
