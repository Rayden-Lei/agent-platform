"""智能体对话路由：以 SSE 流式返回模型生成内容、工具调用过程与运行结果。

需要登录鉴权（JWT 或 API Key），鉴权来源由 get_current_user 统一处理。
"""

import json
import logging
import warnings

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.prebuilt import create_react_agent  # noqa

warnings.filterwarnings("ignore", message=".*create_react_agent.*")

from app.core.deps import get_current_user
from app.core.exceptions import BizError
from app.db.models import AuditLog, User
from app.db.session import SessionLocal, get_db
from app.model_gateway.gateway import guarded_astream
from app.services import chat_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    """对话请求体：message 为用户消息；conversation_id 为空表示开启新对话。"""

    message: str
    conversation_id: int | None = None


def _sse(data: dict) -> str:
    """把数据包装成 SSE 的 data 帧（UTF-8，JSON 序列化）。"""
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: int, data: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """发起对话。

    返回 SSE 事件流，事件类型包括 citations / delta / tool_call / tool_result / done / error；
    客户端中断（停止按钮 / 断网）时生成器被关闭，由 event_stream 的 finally 收尾。
    """
    conversation_id, run_id = chat_service.prepare_chat(db, user.id, agent_id, data.message, data.conversation_id)
    message_text = data.message

    async def event_stream():
        db2 = SessionLocal()
        final_content = ""
        usage_total: dict = {}
        tool_calls_list: list = []
        citations: list = []
        # 已正常收尾（done / failed）。finally 里据此判断是否为客户端中断（停止按钮/断网）导致生成器被关闭。
        finished = False
        try:
            try:
                ctx = chat_service.build_chat_context(db2, agent_id, message_text, conversation_id, role=user.role)
            except BizError as e:
                chat_service.finalize_run(db2, run_id, "failed", error=e.detail)
                finished = True
                yield _sse({"type": "error", "message": e.detail})
                return
            except Exception as e:
                logger.exception("对话上下文构建失败 run_id=%s agent_id=%s", run_id, agent_id)
                chat_service.finalize_run(db2, run_id, "failed", error=str(e))
                finished = True
                yield _sse({"type": "error", "message": "上下文构建失败: " + str(e)[:300]})
                return
            citations = ctx.citations

            # 审计：记录检索鉴权（uid/query/召回 chunk_id/鉴权剔除数）
            db2.add(AuditLog(
                user_id=user.id, username=user.username, action="rag_retrieve", resource="agent", resource_id=agent_id,
                detail={"query": message_text, "recalled_chunk_ids": [c["chunk_id"] for c in ctx.citations], "acl_rejected": ctx.acl_rejected},
            ))
            db2.commit()

            yield _sse({"type": "citations", "citations": ctx.citations})

            graph = create_react_agent(ctx.llm, ctx.tools, prompt=ctx.system_prompt)
            tool_call_acc: dict[int, dict] = {}
            tool_call_by_id: dict[str, int] = {}
            try:
                # 熔断包装：打开期直接以 error 事件结束；首个 chunk 视为成功，建立流之前的异常计入失败
                stream = guarded_astream(ctx.model, graph.astream({"messages": ctx.history_messages}, stream_mode="messages"))
                async for chunk, _meta in stream:
                    if isinstance(chunk, AIMessageChunk):
                        delta = chunk.content
                        if isinstance(delta, str) and delta:
                            final_content += delta
                            yield _sse({"type": "delta", "content": delta})
                        for tc in getattr(chunk, "tool_call_chunks", None) or []:
                            index = tc.get("index")
                            if index is None:
                                continue
                            entry = tool_call_acc.setdefault(index, {"name": "", "args_str": "", "id": ""})
                            if tc.get("name"):
                                entry["name"] = tc["name"]
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                                tool_call_by_id[tc["id"]] = index
                            entry["args_str"] += tc.get("args") or ""
                        for tc in getattr(chunk, "tool_calls", None) or []:
                            tc_id = tc.get("id")
                            if tc_id and tc_id not in tool_call_by_id and (tc.get("args") or tc.get("name")):
                                yield _sse({"type": "tool_call", "name": tc.get("name"), "arguments": tc.get("args", {}), "id": tc_id})
                        um = getattr(chunk, "usage_metadata", None)
                        if um:
                            usage_total = {
                                "prompt_tokens": um.get("input_tokens", 0),
                                "completion_tokens": um.get("output_tokens", 0),
                                "total_tokens": um.get("total_tokens", 0),
                            }
                    elif isinstance(chunk, ToolMessage):
                        tc_id = chunk.tool_call_id
                        index = tool_call_by_id.get(tc_id) if tc_id else None
                        entry = tool_call_acc.get(index) if index is not None else None
                        tool_name = "工具"
                        args = {}
                        if entry:
                            tool_name = entry["name"] or "工具"
                            if entry["args_str"]:
                                try:
                                    args = json.loads(entry["args_str"])
                                except json.JSONDecodeError:
                                    # 模型拼出的参数不是合法 JSON：原样透传给前端展示，不中断对话
                                    logger.warning("工具调用参数不是合法 JSON run_id=%s tool=%s", run_id, entry["name"])
                                    args = {"_raw": entry["args_str"]}
                            yield _sse({"type": "tool_call", "name": tool_name, "arguments": args, "id": tc_id or entry["id"]})
                        result = str(chunk.content)[:200]
                        tool_calls_list.append({"id": tc_id or (entry or {}).get("id"), "name": tool_name, "args": args, "result": result})
                        yield _sse({"type": "tool_result", "content": result, "tool_call_id": tc_id})

                assistant_msg = chat_service.save_assistant_message(db2, conversation_id, final_content, ctx.citations, usage_total, tool_calls_list)
                chat_service.finalize_run(db2, run_id, "success", content=final_content, usage=usage_total)
                finished = True
                yield _sse({"type": "done", "message_id": assistant_msg.id, "run_id": run_id,
                            "conversation_id": conversation_id, "usage": usage_total})
            except Exception as e:
                logger.exception("对话生成失败 run_id=%s agent_id=%s", run_id, agent_id)
                chat_service.finalize_run(db2, run_id, "failed", error=str(e))
                finished = True
                yield _sse({"type": "error", "message": str(e)})
        finally:
            if not finished:
                # 客户端中断：把已生成的部分回答落库，运行记录置为 cancelled，避免永远停在 running
                try:
                    chat_service.finalize_cancelled_chat(db2, run_id, conversation_id, final_content, citations, usage_total, tool_calls_list)
                except Exception:
                    logger.exception("对话中断收尾失败 run_id=%s", run_id)
            db2.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
