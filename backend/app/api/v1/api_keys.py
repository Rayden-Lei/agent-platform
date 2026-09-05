"""API Key 管理路由。

API Key 供外部系统调用执行类接口（如工作流运行）时使用，与 JWT 共用 Authorization: Bearer 头。
本模块仅允许 admin / developer 角色访问；developer 只能看到、操作本人创建的 Key（服务层按归属过滤）。
"""

import ipaddress
from typing import Literal

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
    """

    name: str = Field(min_length=1, max_length=64)
    quota: int = Field(default=1000, ge=0)
    allowed_ips: list[str] = Field(default_factory=list, max_length=MAX_ALLOWED_IPS)
    rate_limit_per_minute: int = Field(default=0, ge=0, le=MAX_RATE_LIMIT_PER_MINUTE)

    @field_validator("allowed_ips")
    @classmethod
    def _check_allowed_ips(cls, value: list[str]) -> list[str]:
        return _validate_cidrs(value)


class ApiKeyUpdate(BaseModel):
    """编辑请求体：全部可选，只更新传了的字段；明文与哈希不可改。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    quota: int | None = Field(default=None, ge=0)
    allowed_ips: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_IPS)
    rate_limit_per_minute: int | None = Field(default=None, ge=0, le=MAX_RATE_LIMIT_PER_MINUTE)

    @field_validator("allowed_ips")
    @classmethod
    def _check_allowed_ips(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _validate_cidrs(value)


class ApiKeyBatchIn(BatchIn):
    action: Literal["enable", "disable", "delete"]


@router.get("")
def list_api_keys(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    is_enabled: bool | None = Query(None),
    user_id: int | None = Query(None, description="按创建人过滤，仅 admin 生效"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """API Key 列表（分页），可按名称、启用状态、创建人过滤；sort 可选 id / name / used / last_used_at / created_at。developer 只看到本人创建的。"""
    return api_key_service.list_api_keys(db, params, user, q, is_enabled, user_id, sort)


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
    """编辑名称、配额、来源白名单、限速。developer 只能改本人创建的（他人的 404）。"""
    return api_key_service.update_api_key(db, key_id, data, user)


@router.post("/{key_id}/toggle")
def toggle_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """启用 / 停用指定 API Key（开关切换）。developer 只能操作本人创建的。"""
    return api_key_service.toggle_api_key(db, key_id, user)


@router.delete("/{key_id}")
def delete_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除指定 API Key。developer 只能删除本人创建的。"""
    api_key_service.delete_api_key(db, key_id, user)
    return {"code": 0, "message": "ok"}
