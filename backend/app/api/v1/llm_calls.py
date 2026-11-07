"""模型调用日志路由（2026-11-08）：查看每次模型调用的完整报文。

只读，AD。为什么单独一页而不是塞进运行详情：调用日志要能跨运行检索
（"哪个地址失败了""这个模型最近返回了什么"），运行详情里按运行看只是其中一种切法。
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params, time_range
from app.db.models import User
from app.db.session import get_db
from app.services import llm_log_service

router = APIRouter(prefix="/llm-calls", tags=["llm-calls"])


@router.get("")
def list_calls(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    run_id: int | None = Query(None, description="只看某次运行"),
    model_id: int | None = Query(None),
    purpose: Literal["chat", "workflow", "debug", "summary", "rewrite", "probe", "embedding"] | None = Query(None),
    status: Literal["success", "error"] | None = Query(None),
    q: str | None = Query(None, max_length=128, description="地址 / 模型名 / 错误信息模糊匹配"),
    start: datetime | None = Query(None, description="起始时间（含），必须带时区"),
    end: datetime | None = Query(None, description="结束时间（不含），必须带时区"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """分页列出模型调用记录（列表不含报文大字段，点开详情才有）。"""
    start, end = time_range(start, end)
    return llm_log_service.list_calls(db, params, run_id=run_id, model_id=model_id, purpose=purpose,
                                      status=status, q=q, start=start, end=end, sort=sort)


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """总调用数 / 失败数 / 今日调用数，以及日志开关状态。固定路径要在 /{call_id} 之前。"""
    return llm_log_service.stats(db)


@router.get("/{call_id}")
def get_call(call_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """单条详情：完整请求体（messages + 工具定义 + 参数）与响应体（含 SSE 原文）。"""
    return llm_log_service.get_call(db, call_id)
