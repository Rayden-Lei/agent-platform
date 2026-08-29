from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas import AgentIn, AgentOut
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return agent_service.list_agents(db)


@router.post("", response_model=AgentOut)
def create_agent(data: AgentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return agent_service.create_agent(db, data, user)


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return agent_service.get_agent(db, agent_id)


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, data: AgentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return agent_service.update_agent(db, agent_id, data)


@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    agent_service.delete_agent(db, agent_id)
    return {"code": 0, "message": "ok"}


@router.post("/{agent_id}/publish", response_model=AgentOut)
def publish_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return agent_service.publish_agent(db, agent_id, user)


@router.get("/{agent_id}/versions")
def list_versions(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return agent_service.list_versions(db, agent_id)


@router.post("/{agent_id}/rollback/{version_id}")
def rollback_agent(agent_id: int, version_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return agent_service.rollback_agent(db, agent_id, version_id)
