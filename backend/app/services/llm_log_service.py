"""模型调用日志服务（2026-11-08）：列表、详情、按运行取调用链。

对外只读。凭据早已在写入时打码，这里不做二次处理 —— 存的是什么就返回什么，
掩盖一层反而让人误以为"日志不全"。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.models import LlmCall

SORTABLE = {"id": LlmCall.id, "started_at": LlmCall.started_at, "duration_ms": LlmCall.duration_ms}

# 列表不返回这两个大字段：一次列表带上百条几 MB 的报文，页面会卡死
_HEAVY = ("request_body", "response_body", "response_text", "reasoning_text")


def _row(c: LlmCall, *, heavy: bool = False) -> dict:
    out = {
        "id": c.id, "run_id": c.run_id, "model_id": c.model_id, "model_name": c.model_name,
        "purpose": c.purpose, "url": c.url, "method": c.method,
        "status": c.status, "http_status": c.http_status, "error": c.error,
        "prompt_tokens": c.prompt_tokens, "completion_tokens": c.completion_tokens,
        "first_token_ms": c.first_token_ms, "duration_ms": c.duration_ms,
        "tool_names": [t.get("name") for t in (c.tools_offered or []) if isinstance(t, dict)],
        "called_tools": [t.get("name") for t in (c.tool_calls or []) if isinstance(t, dict)],
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "truncated": c.truncated,
    }
    if heavy:
        out.update({
            "request_body": c.request_body, "response_body": c.response_body,
            "response_text": c.response_text, "reasoning_text": c.reasoning_text,
            "tools_offered": c.tools_offered or [], "tool_calls": c.tool_calls or [],
        })
    return out


def list_calls(db: Session, params: PageParams, *, run_id: int | None = None, model_id: int | None = None,
               purpose: str | None = None, status: str | None = None, q: str | None = None,
               start: datetime | None = None, end: datetime | None = None,
               sort: SortParams | None = None) -> dict:
    """分页列出调用日志（不含大字段）。q 对 url / model_name / error 模糊匹配。"""
    query = db.query(LlmCall)
    if run_id is not None:
        query = query.filter(LlmCall.run_id == run_id)
    if model_id is not None:
        query = query.filter(LlmCall.model_id == model_id)
    if purpose:
        query = query.filter(LlmCall.purpose == purpose)
    if status:
        query = query.filter(LlmCall.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(LlmCall.url.ilike(like), LlmCall.model_name.ilike(like), LlmCall.error.ilike(like)))
    if start is not None:
        query = query.filter(LlmCall.started_at >= start)
    if end is not None:
        query = query.filter(LlmCall.started_at < end)
    page = paginate(apply_sort(query, sort, SORTABLE, [LlmCall.id.desc()]), params)
    page["items"] = [_row(c) for c in page["items"]]
    return page


def get_call(db: Session, call_id: int) -> dict:
    """单条详情：含完整请求体与响应体。"""
    c = db.get(LlmCall, call_id)
    if c is None:
        raise BizError(404, "调用记录不存在")
    return _row(c, heavy=True)


def stats(db: Session) -> dict:
    """概览：总调用数、失败数、今日调用数。页面头部用。"""
    from sqlalchemy import func

    from app.config import settings
    from app.services import stats_service

    tz = stats_service._tz()
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    total, failed = db.query(func.count(LlmCall.id), func.count(LlmCall.id).filter(LlmCall.status != "success")).one()
    today_count = db.query(func.count(LlmCall.id)).filter(LlmCall.started_at >= today).scalar() or 0
    return {"total": int(total), "failed": int(failed), "today": int(today_count),
            "enabled": bool(settings.LLM_LOG_ENABLED)}
