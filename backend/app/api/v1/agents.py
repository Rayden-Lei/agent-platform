from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import Agent, User
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
    db.commit()
    db.refresh(a)
    return AgentOut.model_validate(a)
