"""分享体验链接（docs/15 3.6，PB-01）：管理侧配置、访客资料与会话、访客令牌校验、访客口径的事件与数据结构、限额。

访客不登录平台（公开模式）或用平台账号（"仅登录"模式）对话；会话与运行走 channel=share / source=share，
公开模式记在分享创建者名下、end_user 是访客 id，"仅登录"模式记在访客本人名下。访客看到的一切都按访客口径裁剪：
不出现系统提示词、模型名、工具入参与返回原文、run_id、用量、kb_id / chunk_id / score。
"""
import secrets
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from zoneinfo import ZoneInfo

from jose import JWTError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core import rate_limiter
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.core.request_context import get_client_ip, get_request_id
from app.core.security import GUEST_TOKEN_TYPE, create_guest_token, decode_token, hash_password, verify_password
from app.db.models import Agent, AgentShare, Conversation, KnowledgeBase, Message, ModelConfig, Run, Tool, User
from app.rag.retriever import kb_allows
from app.runtime.agent_config import load_version_config
from app.services import conversation_service

GUEST_TOKEN_DAYS = 30            # 公开模式访客令牌有效期
GUEST_RENEW_WITHIN = timedelta(days=7)  # 剩余不足 7 天时换发（响应头 X-Share-Token）
SESSION_ATTEMPTS_PER_MINUTE = 5  # 建会话与密码尝试：每条分享 + 来源 IP 每分钟
CREDENTIAL_INVALID = "访问凭证已失效，请重新打开链接"
DEFAULTS = {"is_enabled": False, "access_mode": "public", "expires_at": None, "rate_limit_per_minute": 20,
            "daily_message_limit": 1000, "visitor_daily_limit": 50, "allow_http_tools": False, "show_citations": True}
CONFIG_FIELDS = tuple(DEFAULTS)
# 访客通道原样下发的错误文案（分享与额度类、消息校验类、工具轮数超限）；其余 BizError（熔断、模型不可用——文案带模型名）
# 一律换成通用文案，原文照常进日志与运行记录（docs/15 3.6 错误文案白名单）
GUEST_SAFE_ERRORS = ("链接不存在或已关闭", "链接已过期", "分享不可用", "智能体已下线", "智能体未发布", "今日额度已用完",
                     "你今天的提问次数已用完", "请求过于频繁", "消息不能为空", "超过最大工具调用轮数", "生成失败，请稍后重试")


# ---------- 管理侧 ----------

def _new_code() -> str:
    return secrets.token_urlsafe(12)  # 16 个字符；重置链接时换新


def _share_url(code: str | None) -> str | None:
    """对外链接按 PUBLIC_BASE_URL 拼；没配置时为空，由前端用当前域名拼（PB-07）。"""
    return f"{settings.PUBLIC_BASE_URL}/s/{code}" if code and settings.PUBLIC_BASE_URL else None


def _warnings(db: Session, agent: Agent, access_mode: str, allow_http_tools: bool) -> list[str]:
    """开启前的预检：线上版本绑定了访客检索不到的库、HTTP 工具、模型停用、智能体未发布或已下线。只是提示，不拦保存。"""
    if agent.published_version is None:
        return ["智能体还没有发布：发布后才能开启分享"]
    out = ["智能体已下线：访客打开链接会看到「智能体已下线」"] if agent.status == "offline" else []
    cfg = load_version_config(db, agent.id, agent.published_version)
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(cfg.kb_ids)).all() if cfg.kb_ids else []
    hidden = [k.name for k in kbs if not kb_allows(None, k)]
    if hidden and access_mode == "public":
        out.append(f"匿名访客检索不到这些不公开的知识库：{'、'.join(hidden)}")
    elif hidden:
        out.append(f"这些知识库只对部分角色可见，访客能否检索取决于其本人的角色：{'、'.join(hidden)}")
    tools = [t.name for t in db.query(Tool).filter(Tool.id.in_(cfg.tool_ids))] if cfg.tool_ids else []
    if tools:
        out.append(f"访客对话会调用这些 HTTP 工具：{'、'.join(tools)}" if allow_http_tools else f"绑定的 HTTP 工具不会提供给访客：{'、'.join(tools)}")
    model = db.get(ModelConfig, cfg.model_id)
    if model is not None and not model.is_enabled:
        out.append(f"模型「{model.name}」已停用：访客对话会失败")
    return out


def _share_dict(db: Session, agent: Agent, share: AgentShare | None) -> dict:
    """分享配置（没配置过时是不落库的默认对象）。不返回密码哈希，只给 password_set。"""
    values = DEFAULTS if share is None else {f: getattr(share, f) for f in CONFIG_FIELDS}
    code = share.code if share else None
    return {**values, "expires_at": values["expires_at"].isoformat() if values["expires_at"] else None,
            "agent_id": agent.id, "code": code, "share_url": _share_url(code), "password_set": bool(share and share.password_hash),
            "published": agent.published_version is not None, "agent_status": agent.status,
            "updated_at": share.updated_at.isoformat() if share and share.updated_at else None,
            "warnings": _warnings(db, agent, values["access_mode"], values["allow_http_tools"])}


def _agent(db: Session, agent_id: int) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise BizError(404, "智能体不存在")
    return agent


def get_share(db: Session, agent_id: int) -> dict:
    agent = _agent(db, agent_id)
    return _share_dict(db, agent, db.query(AgentShare).filter(AgentShare.agent_id == agent_id).first())


def update_share(db: Session, agent_id: int, data, user: User) -> dict:
    """整体覆盖分享配置（幂等）。从未发布的智能体不能开启（400）；首次保存生成 code。
    访问密码：请求里没有 password 字段 = 不改，null = 清除，字符串 = 设置。改密码或访问方式时 token_version +1，
    已打开页面的访客下一次请求 401、要重新进入；提交与现值相同的密码不算修改（重复提交同一请求不会把访客踢掉）。
    什么都没变时不写库、不记审计。写审计 share_enable / share_disable / share_update（detail 只记改了哪些字段，不记密码）。
    两个人同时首次保存：后到的撞 agent_id 唯一约束，409 让其刷新。"""
    agent = _agent(db, agent_id)
    if data.is_enabled and agent.published_version is None:
        raise BizError(400, "智能体未发布，不能开启分享")
    share = db.query(AgentShare).filter(AgentShare.agent_id == agent_id).first()
    is_new = share is None
    was_enabled = bool(share and share.is_enabled)
    if is_new:
        share = AgentShare(agent_id=agent_id, code=_new_code(), created_by=user.id, token_version=0)
        db.add(share)
    changed = [f for f in CONFIG_FIELDS if is_new or getattr(share, f) != getattr(data, f)]
    for f in CONFIG_FIELDS:
        setattr(share, f, getattr(data, f))
    if "password" in data.model_fields_set and _password_changes(share.password_hash, data.password):
        share.password_hash = hash_password(data.password) if data.password else None
        changed.append("password")
    if not changed:
        return _share_dict(db, agent, share)
    if not is_new and ("access_mode" in changed or "password" in changed):
        share.token_version += 1
    share.updated_by = user.id
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BizError(409, "分享配置刚被其他人保存过，请刷新后再改")
    action = "share_enable" if data.is_enabled and not was_enabled else "share_disable" if was_enabled and not data.is_enabled else "share_update"
    record_audit(db, user, action, "agent_share", share.id, detail={"agent_id": agent_id, "changed": changed})
    db.refresh(share)
    return _share_dict(db, agent, share)


def _password_changes(current_hash: str | None, new_password: str | None) -> bool:
    if new_password is None:
        return current_hash is not None
    return current_hash is None or not verify_password(new_password, current_hash)


def reset_share(db: Session, agent_id: int, user: User) -> dict:
    """重置链接：换 code、token_version +1，旧链接与已打开的访客立即失效。写审计 share_reset。"""
    agent = _agent(db, agent_id)
    share = db.query(AgentShare).filter(AgentShare.agent_id == agent_id).first()
    if share is None:
        raise BizError(404, "还没有配置过分享")
    share.code = _new_code()
    share.token_version = (share.token_version or 0) + 1
    share.updated_by = user.id
    record_audit(db, user, "share_reset", "agent_share", share.id, detail={"agent_id": agent_id})
    db.refresh(share)
    return _share_dict(db, agent, share)


# ---------- 访客：分享可用性、资料、建会话 ----------

def _available(db: Session, code: str) -> tuple[AgentShare, Agent, User]:
    """分享须存在且已启用（404）、未过期（403「链接已过期」）、智能体在线（403）、创建者未停用（403「分享不可用」）。"""
    share = db.query(AgentShare).filter(AgentShare.code == code).first()
    if share is None or not share.is_enabled:
        raise BizError(404, "链接不存在或已关闭")
    if share.expires_at is not None and share.expires_at <= datetime.now(timezone.utc):
        raise BizError(403, "链接已过期")
    agent = db.get(Agent, share.agent_id)
    if agent is None or agent.published_version is None:
        raise BizError(403, "智能体未发布")
    if agent.status == "offline":
        raise BizError(403, "智能体已下线")
    creator = db.get(User, share.created_by)
    if creator is None or not creator.is_active:
        raise BizError(403, "分享不可用")
    return share, agent, creator


def public_info(db: Session, code: str) -> dict:
    """访客页的资料：只有名称、简介、访问方式与是否要密码（开场白类字段第 2 批起有值）。名称与简介取线上版本。"""
    share, agent, _ = _available(db, code)
    cfg = load_version_config(db, agent.id, agent.published_version)
    return {"agent_name": cfg.name, "description": cfg.description, "opening_statement": None, "starter_questions": [],
            "access_mode": share.access_mode, "password_required": bool(share.password_hash), "show_citations": share.show_citations}


def create_session(db: Session, code: str, password: str | None, platform_user: User | None) -> dict:
    """访客建会话、领访客令牌。按"分享 + 来源 IP"每分钟 ≤5 次（含密码尝试）；有访问密码时须正确（401）；
    "仅登录"模式须带平台 JWT（401「需要登录后访问」），令牌记 uid 与签发时的 uver、有效期同平台 JWT、不换发；
    公开模式 30 天、每次新建一个访客 id（前端按链接存令牌，同一浏览器复用）。"""
    share, _, _ = _available(db, code)
    limited = rate_limiter.check("share_ip", f"{share.id}:{get_client_ip() or 'unknown'}", SESSION_ATTEMPTS_PER_MINUTE)
    if not limited.allowed:
        raise rate_limiter.limit_exceeded(limited)
    if share.access_mode == "login" and platform_user is None:
        raise BizError(401, "需要登录后访问")
    if share.password_hash and not (password and verify_password(password, share.password_hash)):
        raise BizError(401, "访问密码错误")
    now = datetime.now(timezone.utc)
    if share.access_mode == "login":
        visitor_id = f"u{platform_user.id}"
        expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        claims = {"sid": share.id, "vid": visitor_id, "ver": share.token_version, "uid": platform_user.id, "uver": platform_user.token_version}
    else:
        visitor_id = "v_" + secrets.token_hex(8)
        expires = now + timedelta(days=GUEST_TOKEN_DAYS)
        claims = {"sid": share.id, "vid": visitor_id, "ver": share.token_version}
    return {"guest_token": create_guest_token(claims, expires), "visitor_id": visitor_id, "expires_at": expires.isoformat()}


# ---------- 访客令牌校验（docs/15 3.6：所有访客接口除资料与建会话外都走这一个函数） ----------

@dataclass
class Guest:
    share: AgentShare
    agent_id: int
    visitor_id: str
    user: User | None          # "仅登录"模式的访客本人（库里的当前值）；公开模式为空
    creator: User
    renewed_token: str | None  # 公开模式剩余不足 7 天时换发的新令牌，路由放进响应头 X-Share-Token

    @property
    def role(self) -> str | None:
        """检索与工具判定用的角色：匿名为空（只放行公开内容）；登录访客取库里的当前角色，降级后下一轮立即收窄。"""
        return self.user.role if self.user else None

    def caller(self) -> conversation_service.Caller:
        if self.user is not None:
            return conversation_service.Caller(conversation_service.CHANNEL_SHARE, self.user.id, share_id=self.share.id)
        return conversation_service.Caller(conversation_service.CHANNEL_SHARE, self.creator.id, end_user=self.visitor_id, share_id=self.share.id)


def authenticate_guest(db: Session, code: str, token: str | None) -> Guest:
    """按顺序校验，任何一步不过 401「访问凭证已失效，请重新打开链接」（分享本身不可用的按 _available 的 404 / 403）：
    验签与过期、typ=share_guest；sid 等于 URL 里 code 对应的分享（否则拿分享 A 的令牌能调分享 B）；ver 等于分享当前的
    token_version；"仅登录"模式按 uid 回库取用户，须启用且 token_version 等于 uver（停用、重置密码、改密都吊销）。"""
    if not token:
        raise BizError(401, CREDENTIAL_INVALID)
    try:
        claims = decode_token(token)
    except JWTError:
        raise BizError(401, CREDENTIAL_INVALID)
    if claims.get("typ") != GUEST_TOKEN_TYPE:
        raise BizError(401, CREDENTIAL_INVALID)
    share, agent, creator = _available(db, code)
    if claims.get("sid") != share.id or claims.get("ver") != share.token_version or not claims.get("vid"):
        raise BizError(401, CREDENTIAL_INVALID)
    user = None
    if share.access_mode == "login":
        user = db.get(User, claims.get("uid")) if claims.get("uid") else None
        if user is None or not user.is_active or claims.get("uver") != user.token_version:
            raise BizError(401, CREDENTIAL_INVALID)
    renewed = None
    expires = datetime.fromtimestamp(claims["exp"], timezone.utc)
    if user is None and expires - datetime.now(timezone.utc) < GUEST_RENEW_WITHIN:
        new_expires = datetime.now(timezone.utc) + timedelta(days=GUEST_TOKEN_DAYS)
        renewed = create_guest_token({k: claims[k] for k in ("sid", "vid", "ver")}, new_expires)
    return Guest(share, agent.id, claims["vid"], user, creator, renewed)


# ---------- 限额 ----------

def _today_start() -> datetime:
    """按 REPORT_TIMEZONE 切天（与运营统计同一口径），返回 UTC 时间。"""
    tz = ZoneInfo(settings.REPORT_TIMEZONE)
    return datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def check_chat_quota(db: Session, guest: Guest) -> None:
    """访客对话前的额度：链接每分钟（share）、每位访客每分钟（share_v）、来源 IP 每分钟（ip，防一个 IP 换着令牌绕开 share_v）；
    链接每天总量与每位访客每天量用数据库计数（Redis 故障时照样生效）。超限 429，不建运行记录。
    成本的硬上限是链接的每日总量：访客换令牌能绕开"每位访客每日量"，绕不开它。"""
    share = guest.share
    for scope, key, limit in (("share", str(share.id), share.rate_limit_per_minute),
                              ("share_v", f"{share.id}:{guest.visitor_id}", settings.SHARE_VISITOR_PER_MINUTE),
                              ("ip", get_client_ip() or "unknown", settings.RATE_LIMIT_IP_PER_MINUTE)):
        result = rate_limiter.check(scope, key, limit)
        if not result.allowed:
            raise rate_limiter.limit_exceeded(result)
    since = _today_start()
    if db.query(func.count(Run.id)).filter(Run.share_id == share.id, Run.started_at >= since).scalar() >= share.daily_message_limit:
        raise BizError(429, "今日额度已用完，请明天再试")
    mine = conversation_service.owned_conversations(db, guest.caller()).with_entities(Conversation.id).order_by(None).subquery()
    sent = db.query(func.count(Message.id)).filter(Message.conversation_id.in_(db.query(mine.c.id)), Message.role == "user",
                                                   Message.created_at >= since).scalar()
    if sent >= share.visitor_daily_limit:
        raise BizError(429, "你今天的提问次数已用完，请明天再试")


# ---------- 访客口径：事件、错误、会话与消息 ----------

def guest_error_text(message: str) -> str:
    if any(message.startswith(p) for p in GUEST_SAFE_ERRORS):
        return message
    return f"服务暂时不可用，请稍后重试（trace: {get_request_id()}）"


async def guest_events(events: AsyncIterator[dict], show_citations: bool) -> AsyncIterator[dict]:
    """把执行器（或幂等回放）的事件裁成访客口径：引用只给文档名与内容且受 show_citations 控制；工具只给名称；
    done 不带 run_id 与用量；error 按白名单映射。客户端断开时关闭内层执行器，让它照常收尾。"""
    async with aclosing(events) as inner:
        async for e in inner:
            kind = e["type"]
            if kind == "citations":
                yield {"type": kind, "citations": [{"doc_name": c.get("doc_name"), "content": c.get("content")} for c in e["citations"]] if show_citations else []}
            elif kind == "delta":
                yield e
            elif kind == "tool_call":
                yield {"type": kind, "id": e.get("id"), "name": e.get("name")}
            elif kind == "tool_result":
                yield {"type": kind, "tool_call_id": e.get("tool_call_id")}
            elif kind == "done":
                yield {"type": kind, "message_id": e.get("message_id"), "conversation_id": e.get("conversation_id")}
            elif kind == "error":
                yield {"type": kind, "message": guest_error_text(e.get("message") or "")}


def list_guest_conversations(db: Session, guest: Guest, params: PageParams, q: str | None = None) -> dict:
    """本访客自己的会话，可按标题模糊搜索（访客专用结构：{id, title, message_count, created_at, updated_at}，不含 summary 等）。"""
    page = paginate(conversation_service.owned_conversations(db, guest.caller(), q=q), params)
    ids = [c.id for c in page["items"]]
    counts = dict(db.query(Message.conversation_id, func.count(Message.id)).filter(Message.conversation_id.in_(ids)).group_by(Message.conversation_id).all()) if ids else {}
    page["items"] = [{"id": c.id, "title": c.title, "message_count": int(counts.get(c.id, 0)),
                      "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat()} for c in page["items"]]
    return page


def list_guest_messages(db: Session, guest: Guest, conversation_id: int) -> list[dict]:
    """本访客会话里的消息（访客专用结构）：{id, role, content, created_at, citations, tool_names}——引用只有文档名与内容
    （show_citations 关闭时为空数组），工具只有名称；不含 token_usage、run_id、工具入参与结果。"""
    conversation_service.get_owned_conversation(db, conversation_id, guest.caller())
    rows = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    show = guest.share.show_citations
    return [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat(),
             "citations": [{"doc_name": c.get("doc_name"), "content": c.get("content")} for c in (m.citations or [])] if show else [],
             "tool_names": [t.get("name") for t in (m.tool_calls or []) if t.get("name")]} for m in rows]


def delete_guest_conversation(db: Session, guest: Guest, conversation_id: int) -> None:
    conv = conversation_service.get_owned_conversation(db, conversation_id, guest.caller())
    db.delete(conv)
    db.commit()
