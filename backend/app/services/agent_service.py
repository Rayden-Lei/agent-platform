from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.db.models import Agent, AgentVersion, User
from app.schemas import AgentIn


def list_agents(db: Session) -> list[Agent]:
    return db.query(Agent).order_by(Agent.id).all()


def create_agent(db: Session, data: AgentIn, user: User) -> Agent:
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
    return a


def get_agent(db: Session, agent_id: int) -> Agent:
    a = db.get(Agent, agent_id)
    if a is None:
        raise BizError(404, "智能体不存在")
    return a


def update_agent(db: Session, agent_id: int, data: AgentIn) -> Agent:
    a = get_agent(db, agent_id)
    for field, value in data.model_dump().items():
        setattr(a, field, value)
    db.commit()
    db.refresh(a)
    return a


def delete_agent(db: Session, agent_id: int) -> None:
    a = get_agent(db, agent_id)
    # agent_versions / conversations / messages / runs / run_nodes 由数据库外键 CASCADE 级联删除
    db.delete(a)
    db.commit()


def publish_agent(db: Session, agent_id: int, user: User) -> Agent:
    a = get_agent(db, agent_id)
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
    record_audit(db, user, "publish", "agent", a.id, detail={"name": a.name, "version": a.version})
    return a


def list_versions(db: Session, agent_id: int) -> list[dict]:
    get_agent(db, agent_id)
    rows = db.query(AgentVersion).filter(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()).all()
    return [{"id": v.id, "version": v.version, "snapshot": v.snapshot, "created_at": v.created_at.isoformat()} for v in rows]


def rollback_agent(db: Session, agent_id: int, version_id: int) -> Agent:
    a = get_agent(db, agent_id)
    av = db.get(AgentVersion, version_id)
    if av is None or av.agent_id != agent_id:
        raise BizError(404, "版本不存在")
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
    return a
