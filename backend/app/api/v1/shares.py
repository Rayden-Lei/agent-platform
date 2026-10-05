"""分享体验链接的管理路由（docs/15 3.6，PB-01）：读取、整体覆盖、重置。admin / developer，只认 JWT（API Key 403）。

访客侧的接口在 public_shares.py（不要 JWT）。业务规则（发布前不能开启、改密码吊销访客令牌、预检、审计）都在 share_service。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.services import share_service

router = APIRouter(prefix="/agents/{agent_id}/share", tags=["shares"])

BCRYPT_MAX_BYTES = 72  # bcrypt 5 对超过 72 字节的口令直接抛错，中文一个字占 3 字节，按字节数校验


class ShareIn(BaseModel):
    """分享配置，整体覆盖：除 password 外都必须给（expires_at 可以是 null = 不过期）。
    password：不带这个字段 = 不改；null = 清除；字符串（4～64 字）= 设置。改密码或访问方式会让已打开页面的访客重新进入。
    限额一律显式范围，没有"0 表示不限"（docs/15 3.6）。"""

    is_enabled: bool
    access_mode: Literal["public", "login"]
    password: str | None = Field(None, min_length=4, max_length=64)
    expires_at: datetime | None
    rate_limit_per_minute: int = Field(ge=1, le=600)
    daily_message_limit: int = Field(ge=1, le=100000)
    visitor_daily_limit: int = Field(ge=1, le=1000)
    allow_http_tools: bool
    show_citations: bool

    @field_validator("password")
    @classmethod
    def _password_bytes(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError(f"访问密码过长（不超过 {BCRYPT_MAX_BYTES} 字节，一个汉字算 3 字节）")
        return value

    @field_validator("expires_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        # 不带时区的时间按哪个时区解释都是猜，直接 422（前端用 ISO 8601 带偏移量提交）
        if value is not None and value.tzinfo is None:
            raise ValueError("有效期必须带时区，如 2026-10-31T23:59:59+08:00")
        return value


@router.get("")
def get_share(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """分享配置；没配置过时返回 is_enabled=false 的默认对象（不落库，code 与 share_url 为空）。带预检 warnings。"""
    return share_service.get_share(db, agent_id)


@router.put("")
def update_share(agent_id: int, data: ShareIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """整体覆盖分享配置（幂等）。从未发布时开启 400；首次保存生成链接；返回与 GET 同形的配置（含预检 warnings）。"""
    return share_service.update_share(db, agent_id, data, user)


@router.post("/reset")
def reset_share(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """重置链接：换新 code，旧链接与已打开的访客立即失效。没配置过 404。"""
    return share_service.reset_share(db, agent_id, user)
