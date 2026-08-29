import json
import warnings

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent  # noqa

warnings.filterwarnings("ignore", message=".*create_react_agent.*")

from app.config import settings
from app.core.deps import get_current_user
from app.db.models import Agent, Conversation, Message, ModelConfig, Run, Tool, User
from app.db.session import SessionLocal, get_db
from app.model_gateway.gateway import build_llm
from app.rag.retriever import retrieve
from app.tools.langchain_tools import build_tools

router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


def _sse(data: dict) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: int, data: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if agent.status != "published":
        raise HTTPException(status_code=403, detail="智能体未发布")

    conversation = None
    if data.conversation_id:
        conversation = db.get(Conversation, data.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    if conversation is None:
        conversation = Conversation(agent_id=agent_id, user_id=user.id, title=data.message[:30])
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    user_msg = Message(conversation_id=conversation.id, role="user", content=data.message)
    db.add(user_msg)
    run = Run(run_type="chat", agent_id=agent_id, user_id=user.id, status="running", input={"message": data.message})
    db.add(run)
    db.commit()
    db.refresh(run)

    conversation_id = conversation.id
    run_id = run.id
    message_text = data.message

    async def event_stream():
        db2 = SessionLocal()
        try:
            agent2 = db2.get(Agent, agent_id)
            model = db2.get(ModelConfig, agent2.model_id)
            if model is None or not model.is_enabled:
                yield _sse({"type": "error", "message": "模型不可用"})
                return

            llm = build_llm(model)
            tool_dbs = (
                db2.query(Tool).filter(Tool.id.in_(agent2.tool_ids)).all()
                if agent2.tool_ids
                else []
            )
            tools = build_tools(tool_dbs)

            kb_context = ""
            citations = []
            if agent2.kb_ids:
                for kb_id in agent2.kb_ids:
                    for s in retrieve(kb_id, message_text, settings.RAG_TOP_K):
                        citations.append(
                            {"kb_id": kb_id, "doc_name": s["doc_name"], "content": s["content"], "score": s["score"]})
                if citations:
                    kb_context = "以下是与问题相关的知识，请优先参考：\n" + "\n".join(
                        f"[{i + 1}] {c['content']}" for i, c in enumerate(citations)
                    )
            system_prompt = agent2.system_prompt + (("\n\n" + kb_context) if kb_context else "")
            graph = create_react_agent(llm, tools, prompt=system_prompt)

            history = (
                db2.query(Message)
                .filter(Message.conversation_id == conversation_id)
                .order_by(Message.id)
                .all()
            )
            lc_messages = []
            for h in history:
                if h.role == "user":
                    lc_messages.append(HumanMessage(content=h.content))
                elif h.role == "assistant":
                    lc_messages.append(AIMessage(content=h.content))
            lc_messages.append(HumanMessage(content=message_text))

            final_content = ""
            usage_total = {}
            try:
                async for chunk, _meta in graph.astream({"messages": lc_messages}, stream_mode="messages"):
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

                assistant_msg = Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=final_content,
                    citations=citations,
                    token_usage=usage_total,
                )
                db2.add(assistant_msg)
                run2 = db2.get(Run, run_id)
                run2.status = "success"
                run2.output = {"content": final_content}
                run2.token_usage = usage_total
                db2.commit()
                yield _sse({"type": "done", "message_id": assistant_msg.id, "run_id": run_id,
                            "conversation_id": conversation_id, "usage": usage_total})
            except Exception as e:
                run2 = db2.get(Run, run_id)
                if run2:
                    run2.status = "failed"
                    run2.error = str(e)
                    db2.commit()
                yield _sse({"type": "error", "message": str(e)})
        finally:
            db2.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
