import json
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
from app.db.models import User
from app.db.session import SessionLocal, get_db
from app.services import chat_service

router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


def _sse(data: dict) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: int, data: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conversation_id, run_id = chat_service.prepare_chat(db, user.id, agent_id, data.message, data.conversation_id)
    message_text = data.message

    async def event_stream():
        db2 = SessionLocal()
        try:
            try:
                ctx = chat_service.build_chat_context(db2, agent_id, message_text, conversation_id)
            except BizError as e:
                yield _sse({"type": "error", "message": e.detail})
                return

            graph = create_react_agent(ctx.llm, ctx.tools, prompt=ctx.system_prompt)
            final_content = ""
            usage_total = {}
            try:
                async for chunk, _meta in graph.astream({"messages": ctx.history_messages}, stream_mode="messages"):
                    if isinstance(chunk, AIMessageChunk):
                        delta = chunk.content
                        if isinstance(delta, str) and delta:
                            final_content += delta
                            yield _sse({"type": "delta", "content": delta})
                        for tc in getattr(chunk, "tool_calls", None) or []:
                            yield _sse({"type": "tool_call", "name": tc.get("name"), "arguments": tc.get("args", {})})
                        um = getattr(chunk, "usage_metadata", None)
                        if um:
                            usage_total = {
                                "prompt_tokens": um.get("input_tokens", 0),
                                "completion_tokens": um.get("output_tokens", 0),
                                "total_tokens": um.get("total_tokens", 0),
                            }
                    elif isinstance(chunk, ToolMessage):
                        yield _sse({"type": "tool_result", "content": str(chunk.content)[:200]})

                assistant_msg = chat_service.save_assistant_message(db2, conversation_id, final_content, ctx.citations, usage_total)
                chat_service.finalize_run(db2, run_id, "success", content=final_content, usage=usage_total)
                yield _sse({"type": "done", "message_id": assistant_msg.id, "run_id": run_id,
                            "conversation_id": conversation_id, "usage": usage_total})
            except Exception as e:
                chat_service.finalize_run(db2, run_id, "failed", error=str(e))
                yield _sse({"type": "error", "message": str(e)})
        finally:
            db2.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
