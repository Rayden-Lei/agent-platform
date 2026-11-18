"""API Key 管理路由。

API Key 供外部系统调用执行类接口（对话、工作流运行）时使用，与 JWT 共用 Authorization: Bearer 头；
只能调用作用域内的智能体与工作流（docs/15 3.7.1）。本模块仅允许 admin / developer 角色访问；
developer 只能看到、操作本人创建的 Key（服务层按归属过滤）。
"""

import ipaddress
from datetime import datetime, timezone
from typing import Literal, overload

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.services import api_key_service

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

MAX_ALLOWED_IPS = 50
MAX_RATE_LIMIT_PER_MINUTE = 10000
MAX_SCOPE_IDS = 100  # 每类作用域的上限；ID 的存在性与知识库可见性在服务层校验（400）


# 两个请求体共用这一个去重函数：ApiKeyCreate 的字段是非空 list，ApiKeyUpdate 的字段可为 None。
# 用重载说明"传什么回什么"，调用处就不必再判 None —— 实现体本身没有任何变化。
@overload
def _dedupe(ids: list[int]) -> list[int]: ...
@overload
def _dedupe(ids: None) -> None: ...
def _dedupe(ids: list[int] | None) -> list[int] | None:
    """作用域去重保序：重复的 ID 不报错，只存一份。"""
    if ids is None:
        return None
    seen: set[int] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def _validate_expires_at(value: datetime | None) -> datetime | None:
    """有效期校验（422）：必须带时区（不带时区按哪个时区解释都是猜），且必须是未来时间。
    服务端是唯一权威（前端日期选择器只是体验）；空值 = 永不过期，不算"过去的时间"。"""
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("有效期必须带时区，如 2026-12-31T23:59:59+08:00")
    if value <= datetime.now(timezone.utc):
        raise ValueError("有效期必须是未来时间")
    return value


def _validate_cidrs(items: list[str]) -> list[str]:
    """schema 层校验（422）：每项必须是合法 IP 或 CIDR；错误信息指出第几项，便于表单定位。"""
    cleaned = []
    for index, item in enumerate(items, 1):
        value = (item or "").strip()
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise ValueError(f"第 {index} 项不是合法的 IP 或 CIDR：{item!r}")
        cleaned.append(value)
    return cleaned


class ApiKeyIn(BaseModel):
    """创建 API Key 的请求体。

    quota：调用额度上限（默认 1000 次）；allowed_ips：来源白名单（空 = 不限制）；
    rate_limit_per_minute：每分钟限速（0 = 用全局 RATE_LIMIT_API_KEY_PER_MINUTE）。
    agent_ids / workflow_ids / kb_ids：资源作用域（docs/15 3.7.1）——只能调这些智能体与工作流，检索时除公开库外只放行
    kb_ids 内的库；三者至少一个非空（400，2026-10-05 起，此前 Key 能调归属人能调的一切）。
    """

    name: str = Field(min_length=1, max_length=64)
    # None = 不限次数（docs/15 PB-11，2026-11-18 起）；0 = 一次都不能调。此前 0 被页面当成"不限"、服务端却是全拒
    quota: int | None = Field(default=1000, ge=0)
    allowed_ips: list[str] = Field(default_factory=list, max_length=MAX_ALLOWED_IPS)
    rate_limit_per_minute: int = Field(default=0, ge=0, le=MAX_RATE_LIMIT_PER_MINUTE)
    agent_ids: list[int] = Field(default_factory=list, max_length=MAX_SCOPE_IDS)
    workflow_ids: list[int] = Field(default_factory=list, max_length=MAX_SCOPE_IDS)
    kb_ids: list[int] = Field(default_factory=list, max_length=MAX_SCOPE_IDS)
    owner_user_id: int | None = None  # 代发给哪个用户（仅 admin，docs/15 D-15）；不传归属当前用户
    expires_at: datetime | None = None  # 有效期（不传 = 永不过期）；必须是未来时间，否则 422

    @field_validator("allowed_ips")
    @classmethod
    def _check_allowed_ips(cls, value: list[str]) -> list[str]:
        return _validate_cidrs(value)

    @field_validator("expires_at")
    @classmethod
    def _check_expires_at(cls, value: datetime | None) -> datetime | None:
        return _validate_expires_at(value)

    @field_validator("agent_ids", "workflow_ids", "kb_ids")
    @classmethod
    def _unique(cls, value: list[int]) -> list[int]:
        return _dedupe(value)


class ApiKeyUpdate(BaseModel):
    """编辑请求体：全部可选，只更新传了的字段；明文与哈希不可改。改作用域时按改后的三类整体校验（至少一个非空）。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    # quota 的 null 是有意义的值（改为不限次数），不是"未提供"：服务层用 model_fields_set 区分两者
    quota: int | None = Field(default=None, ge=0)
    allowed_ips: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_IPS)
    rate_limit_per_minute: int | None = Field(default=None, ge=0, le=MAX_RATE_LIMIT_PER_MINUTE)
    agent_ids: list[int] | None = Field(default=None, max_length=MAX_SCOPE_IDS)
    workflow_ids: list[int] | None = Field(default=None, max_length=MAX_SCOPE_IDS)
    kb_ids: list[int] | None = Field(default=None, max_length=MAX_SCOPE_IDS)
    # 有效期：不传 = 不改；显式 null = 清除（永不过期）；传时间 = 必须是未来时间（422）
    expires_at: datetime | None = None

    @field_validator("allowed_ips")
    @classmethod
    def _check_allowed_ips(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _validate_cidrs(value)

    @field_validator("expires_at")
    @classmethod
    def _check_expires_at(cls, value: datetime | None) -> datetime | None:
        return _validate_expires_at(value)

    @field_validator("agent_ids", "workflow_ids", "kb_ids")
    @classmethod
    def _unique(cls, value: list[int] | None) -> list[int] | None:
        return _dedupe(value)


class ApiKeyBatchIn(BatchIn[Literal["enable", "disable", "delete"]]):
    """action 只接受 "enable", "disable", "delete"，其余值 422。"""


@router.get("")
def list_api_keys(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    is_enabled: bool | None = Query(None),
    user_id: int | None = Query(None, description="按创建人过滤，仅 admin 生效"),
    agent_id: int | None = Query(None, description="只取作用域含该智能体的"),
    workflow_id: int | None = Query(None, description="只取作用域含该工作流的"),
    kb_id: int | None = Query(None, description="只取作用域含该知识库的"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """API Key 列表（分页），可按名称、启用状态、创建人、作用域里的资源过滤；sort 可选 id / name / used / last_used_at / created_at。
    developer 只看到本人创建的。"""
    return api_key_service.list_api_keys(db, params, user, q, is_enabled, user_id, sort, agent_id, workflow_id, kb_id)


@router.post("")
def create_api_key(data: ApiKeyIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建 API Key。创建后返回密钥信息，供调用方保存。"""
    return api_key_service.create_api_key(db, data, user)


# 固定路径必须声明在 /{key_id} 之前
@router.post("/batch")
def batch_api_keys(data: ApiKeyBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量启用 / 停用 / 删除：逐条独立执行并返回成功与失败清单；developer 对他人 Key 的 404 进失败清单。"""
    return run_batch(db, data.unique_ids(), lambda key_id: api_key_service.apply_batch_action(db, key_id, data.action, user))


@router.put("/{key_id}")
def update_api_key(key_id: int, data: ApiKeyUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """编辑名称、配额、来源白名单、限速、有效期。只更新传了的字段（显式 null 清除有效期 / 改为不限配额）。
    developer 只能改本人创建的（他人的 404）。"""
    return api_key_service.update_api_key(db, key_id, data, user)


@router.post("/{key_id}/toggle")
def toggle_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """启用 / 停用指定 API Key（开关切换）。developer 只能操作本人创建的。"""
    return api_key_service.toggle_api_key(db, key_id, user)


@router.post("/{key_id}/rotate")
def rotate_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """轮换密钥（docs/15 PB-11）：换一把新明文，其余设置不变；旧明文立即失效，新明文只在此响应返回一次。

    原地轮换（不新建行）的理由见 api_key_service.rotate_api_key。developer 只能轮换本人创建的（他人的 404）。
    """
    return api_key_service.rotate_api_key(db, key_id, user)


@router.delete("/{key_id}")
def delete_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除指定 API Key。developer 只能删除本人创建的。"""
    api_key_service.delete_api_key(db, key_id, user)
    return {"code": 0, "message": "ok"}
