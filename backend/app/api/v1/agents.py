from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import Agent, AgentVersion, Conversation, Message, Run, RunNode, User
from app.db.session import get_db
from app.schemas import AgentIn, AgentOut

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return db.query(Agent).order_by(Agent.id).all()


@router.post("", response_model=AgentOut)
def create_agent(data: AgentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    a = Agent(
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        model_id=data.model_id,
        params=data.params,
        kb_ids=data.kb_ids,
        tool_ids=data.tool_ids,
        workflow_id=data.workflow_id,
        created_by=user.id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return AgentOut.model_validate(a)


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    a = db.get(Agent, agent_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="智能体不存在")
    return AgentOut.model_validate(a)


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, data: AgentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    a = db.get(Agent, agent_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="智能体不存在")
    for field, value in data.model_dump().items():
        setattr(a, field, value)
    db.commit()
    db.refresh(a)
    return AgentOut.model_validate(a)


@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    a = db.get(Agent, agent_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="智能体不存在")
    db.query(AgentVersion).filter(AgentVersion.agent_id == agent_id).delete(synchronize_session=False)
    conv_ids = [c.id for c in db.query(Conversation).filter(Conversation.agent_id == agent_id).all()]
    if conv_ids:
        db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.agent_id == agent_id).delete(synchronize_session=False)
    run_ids = [r.id for r in db.query(Run).filter(Run.agent_id == agent_id).all()]
    if run_ids:
        db.query(RunNode).filter(RunNode.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(Run).filter(Run.agent_id == agent_id).delete(synchronize_session=False)
    db.delete(a)
    db.commit()
    return {"code": 0, "message": "ok"}


@router.post("/{agent_id}/publish", response_model=AgentOut)
def publish_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    a = db.get(Agent, agent_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="智能体不存在")
    a.status = "published"
    a.version = (a.version or 0) + 1
    db.add(AgentVersion(
        agent_id=a.id,
        version=a.version,
        snapshot={
            "name": a.name,
            "description": a.description,
            "system_prompt": a.system_prompt,
            "model_id": a.model_id,
            "params": a.params,
            "kb_ids": a.kb_ids,
            "tool_ids": a.tool_ids,
            "workflow_id": a.workflow_id,
        },
    ))
    db.commit()
    db.refresh(a)
    return AgentOut.model_validate(a)


@router.get("/{agent_id}/versions")
def list_versions(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(AgentVersion).filter(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()).all()
    return [{"id": v.id, "version": v.version, "snapshot": v.snapshot, "created_at": v.created_at.isoformat()} for v in rows]


@router.post("/{agent_id}/rollback/{version_id}")
def rollback_agent(agent_id: int, version_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    a = db.get(Agent, agent_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="智能体不存在")
    av = db.get(AgentVersion, version_id)
    if av is None or av.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    snap = av.snapshot or {}
    a.name = snap.get("name", a.name)
    a.description = snap.get("description", a.description)
    a.system_prompt = snap.get("system_prompt", a.system_prompt)
    a.model_id = snap.get("model_id", a.model_id)
    a.params = snap.get("params", a.params)
    a.kb_ids = snap.get("kb_ids", a.kb_ids)
    a.tool_ids = snap.get("tool_ids", a.tool_ids)
    a.workflow_id = snap.get("workflow_id", a.workflow_id)
    a.version = (a.version or 0) + 1
    db.commit()
    db.refresh(a)
    return AgentOut.model_validate(a)
