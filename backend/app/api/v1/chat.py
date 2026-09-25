"""智能体对话路由：以 SSE 流式返回模型生成内容、工具调用过程与运行结果。

需要登录鉴权（JWT 或 API Key），鉴权来源由 get_current_user 统一处理。
这里只做三件事：入参校验、建会话与运行记录（错误以 HTTP 状态码返回），以及把执行器的事件转成 SSE 帧；
流式执行在 services/chat_runner（2026-09-25 从本文件下沉，调试、分享访客也要复用它）。
"""

import json
from contextlib import aclosing

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services import chat_runner, chat_service

router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    """对话请求体：message 为用户消息（1～CHAT_MESSAGE_MAX_CHARS 字符，全是空白由服务层返回 400）；conversation_id 为空表示开启新对话。"""

    message: str = Field(min_length=1, max_length=settings.CHAT_MESSAGE_MAX_CHARS)
    conversation_id: int | None = None


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
async def chat(agent_id: int, data: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """发起对话。

    返回 SSE 事件流，事件类型包括 citations / delta / tool_call / tool_result / done / error（docs/04 第 5 节）。
    空消息、智能体不存在或未发布、会话不属于本人或不属于该智能体，都在建流之前以 HTTP 状态码拒绝，不写任何数据。
    """
    # 同步的库操作放线程池，不阻塞事件循环
    conversation_id, run_id = await run_in_threadpool(chat_service.prepare_chat, db, user.id, agent_id, data.message, data.conversation_id)
    turn = chat_runner.ChatTurn(agent_id=agent_id, user_id=user.id, role=user.role, message=data.message,
                                conversation_id=conversation_id, run_id=run_id)
    return StreamingResponse(_sse_stream(chat_runner.stream_chat(turn)), media_type="text/event-stream")
