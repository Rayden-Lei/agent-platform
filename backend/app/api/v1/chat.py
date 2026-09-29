"""智能体对话路由：以 SSE 流式返回模型生成内容、工具调用过程与运行结果。

对话接口需要登录鉴权（JWT 或 API Key），鉴权来源由 get_current_user 统一处理；装配页调试接口只给 admin / developer 的 JWT。
这里只做三件事：入参校验、建会话与运行记录（错误以 HTTP 状态码返回），以及把执行器的事件转成 SSE 帧；
流式执行在 services/chat_runner（2026-09-25 从本文件下沉，调试、分享访客也要复用它）。
"""

import json
from contextlib import aclosing
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.deps import get_current_user, is_api_key_request, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas import AgentIn
from app.services import chat_runner, chat_service

router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    """对话请求体：message 为用户消息（1～CHAT_MESSAGE_MAX_CHARS 字符，全是空白由服务层返回 400）；conversation_id 为空表示开启新对话。"""

    message: str = Field(min_length=1, max_length=settings.CHAT_MESSAGE_MAX_CHARS)
    conversation_id: int | None = None


# 调试历史由前端保存并随请求带上（docs/15 3.4）：条数与总长都要有界，否则一次请求就能塞进任意大的上下文
DEBUG_HISTORY_MAX_ITEMS = 40
DEBUG_HISTORY_MAX_CHARS = 64000


class DebugHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class DebugChatIn(BaseModel):
    """装配页调试请求体。config_source：inline 用请求里的 config（编辑器当前内容，含未保存修改）、draft 用已保存的草稿、
    live 用线上版本；只有 inline 带 config，其余带了 422。config 结构同 PUT /agents/{id}（不含 expected_updated_at）。"""

    message: str = Field(min_length=1, max_length=settings.CHAT_MESSAGE_MAX_CHARS)
    history: list[DebugHistoryItem] = Field(default_factory=list, max_length=DEBUG_HISTORY_MAX_ITEMS)
    config_source: Literal["inline", "draft", "live"] = "inline"
    config: AgentIn | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.config_source == "inline" and self.config is None:
            raise ValueError("config_source 为 inline 时必须带 config")
        if self.config_source != "inline" and self.config is not None:
            raise ValueError("只有 config_source 为 inline 时才能带 config")
        if sum(len(h.content) for h in self.history) > DEBUG_HISTORY_MAX_CHARS:
            raise ValueError(f"调试历史总长不能超过 {DEBUG_HISTORY_MAX_CHARS} 字")
        return self


def _sse(data: dict) -> str:
    """把数据包装成 SSE 的 data 帧（UTF-8，JSON 序列化）。"""
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


async def _sse_stream(events):
    """执行器事件 → SSE 帧。客户端断开时显式关闭执行器，让它的 finally 立刻收尾（部分回答落库、运行记录置 cancelled），
    而不是等垃圾回收时才关。"""
    async with aclosing(events) as it:
        async for event in it:
            yield _sse(event)


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: int, data: ChatIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """发起对话。

    返回 SSE 事件流，事件类型包括 citations / delta / tool_call / tool_result / done / error（docs/04 第 5 节）。
    空消息、智能体不存在或未发布、会话不属于本人或不属于该智能体，都在建流之前以 HTTP 状态码拒绝，不写任何数据。
    """
    via_api_key = is_api_key_request(request)
    # 同步的库操作放线程池，不阻塞事件循环
    prepared = await run_in_threadpool(
        chat_service.prepare_chat, db, user.id, agent_id, data.message, data.conversation_id,
        "api_key" if via_api_key else "chat", getattr(request.state, "api_key_id", None) if via_api_key else None,
    )
    turn = chat_runner.ChatTurn(agent_id=agent_id, user_id=user.id, role=user.role, message=data.message,
                                conversation_id=prepared.conversation_id, run_id=prepared.run_id, agent_version=prepared.agent_version)
    return StreamingResponse(_sse_stream(chat_runner.stream_chat(turn)), media_type="text/event-stream")


@router.post("/agents/{agent_id}/debug-chat")
async def debug_chat(agent_id: int, data: DebugChatIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """装配页当场调试（docs/15 3.4，FR-041；admin / developer，只认 JWT，API Key 403）。

    草稿与未保存的配置也能对话；事件在线上 6 类之外多出 prompt（实际系统提示词）与 trace（调用链步骤），
    done 不带会话与消息 ID、多带 metrics。运行记录 source=debug，不建会话、不落消息，运营指标不计。
    配置校验不过（与保存同一口径）等拒绝都在建流之前以 HTTP 状态码返回，不建运行记录。
    """
    turn = await run_in_threadpool(chat_service.prepare_debug, db, user, agent_id, data.message,
                                   [h.model_dump() for h in data.history], data.config_source, data.config)
    return StreamingResponse(_sse_stream(chat_runner.stream_debug(turn)), media_type="text/event-stream")
