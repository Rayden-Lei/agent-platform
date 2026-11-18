"""对话日志审阅路由（docs/15 PB-09 / OP-06）：管理面查看全部会话，含分享访客与 API Key 发起的。

为什么单独一个模块而不是并进 /conversations：那里是"当前调用方自己的会话"，归属判定
（conversation_service.owns / _owned_filter）是全仓唯一的一处，管理面不做归属判定，
两者放同一个文件会让"这里的 404 到底是不存在还是不属于你"变得含糊。
仅 admin / developer 的登录请求可访问（API Key 403，由 require_roles 统一拒绝）。

审计：列表不逐条记（会把审计页刷满），查看具体会话的消息才记 —— 看他人会话写
action=view / resource=conversation，据此能追到谁看过谁的会话。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params, time_range
from app.db.models import User
from app.db.session import get_db
from app.schemas import CALLER_ID_PATTERN
from app.services import conversation_log_service

router = APIRouter(prefix="/conversation-logs", tags=["conversation-logs"])

# 通道与对话类型的枚举：取值非法由 Literal 在入口层 422（与 /conversations、/runs 同口径）
Channel = Literal["ui", "api", "share"]
Kind = Literal["model", "agent", "workflow"]


@router.get("")
def list_conversation_logs(
    params: PageParams = Depends(page_params),
    channel: Channel | None = Query(None, description="会话通道：ui 界面 / api API Key / share 分享访客"),
    kind: Kind | None = Query(None, description="对话类型；按对象过滤时必须同时给"),
    target_id: int | None = Query(None, description="按对话对象过滤（模型 / 智能体 / 工作流的 id），必须同时给 kind"),
    user_id: int | None = Query(None, description="按发起人过滤：界面会话是本人，API Key 与分享公开模式的会话是 Key 归属人 / 分享创建者"),
    end_user: str | None = Query(None, pattern=CALLER_ID_PATTERN, description="终端用户标识（API Key 背后的终端用户）或分享公开模式的访客 id"),
    q: str | None = Query(None, max_length=64, description="标题模糊匹配"),
    created_from: datetime | None = Query(None, description="创建时间下界（含），ISO 8601 带时区"),
    created_to: datetime | None = Query(None, description="创建时间上界（不含），ISO 8601 带时区"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """全部会话的列表（分页），按更新时间倒序；每项带通道、归属人、API Key、终端用户 / 访客、对象名与消息数。

    分页与筛选参数与既有列表接口一致（page / page_size / q / ...），时间区间左闭右开。
    这里的列表本身不写审计：逐条记会把审计页刷满，真正要看的是"谁看了谁的会话内容"。
    """
    created_from, created_to = time_range(created_from, created_to)
    return conversation_log_service.list_conversation_logs(
        db, params, channel=channel, kind=kind, target_id=target_id, user_id=user_id, end_user=end_user,
        q=q, created_from=created_from, created_to=created_to)


@router.get("/{conversation_id}/messages")
def list_conversation_messages(
    conversation_id: int,
    full_tool_results: bool = Query(False, description="返回落库的完整工具结果（≤ 8000 字）；不带时为展示口径（200 字）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """任意会话的消息（只读），字段与 /conversations/{id}/messages 完全一致（同一份序列化）。

    查看他人会话写审计 view / conversation。工具结果默认截到 200 字（与实时事件同长），
    排查时带 full_tool_results=true 取库里那份（≤ 8000）；本接口已限 admin / developer，
    不再额外判身份 —— 与 /conversations 的 full_allowed 是同一个角色集合。
    """
    return conversation_log_service.list_conversation_messages(db, conversation_id, user, full_tool_results)
