from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import Agent, AgentVersion, User
from app.schemas import AgentIn


def list_agents(db: Session, params: PageParams, q: str = None, status: str = None) -> dict:
    """分页列出智能体：q 对名称模糊匹配，status 精确过滤（如 published / draft）。"""
    query = db.query(Agent)
    if q:
        query = query.filter(Agent.name.ilike(f"%{q}%"))
    if status:
        query = query.filter(Agent.status == status)
    return paginate(query.order_by(Agent.id), params)


def create_agent(db: Session, data: AgentIn, user: User) -> Agent:
    """新建智能体：初始为草稿态（draft），created_by 记录创建人。"""
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
    """按 ID 取智能体，不存在抛 BizError(404)。"""
    a = db.get(Agent, agent_id)
    if a is None:
        raise BizError(404, "智能体不存在")
    return a


def update_agent(db: Session, agent_id: int, data: AgentIn) -> Agent:
    """整表覆盖式更新：把请求体所有字段写回（草稿态编辑），不校验发布状态。"""
    a = get_agent(db, agent_id)
    for field, value in data.model_dump().items():
        setattr(a, field, value)
    db.commit()
    db.refresh(a)
    return a


def delete_agent(db: Session, agent_id: int) -> None:
    """删除智能体，关联数据由数据库外键 CASCADE 级联删除。"""
    a = get_agent(db, agent_id)
    # agent_versions / conversations / messages / runs / run_nodes 由数据库外键 CASCADE 级联删除
    db.delete(a)
    db.commit()


def publish_agent(db: Session, agent_id: int, user: User) -> Agent:
    """发布智能体：状态置 published、版本号 +1，并把当前配置整体写入 AgentVersion 快照供回滚。"""
    a = get_agent(db, agent_id)
    a.status = "published"
    # 每次发布都把"当前配置"固化成一份版本快照，之后可回滚到任意历史版本
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


def list_versions(db: Session, agent_id: int, params: PageParams) -> dict:
    """分页列出发布版本（按版本号倒序），先校验智能体存在。"""
    get_agent(db, agent_id)
    query = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc(), AgentVersion.id.desc())
    )
    return paginate(query, params, lambda v: {"id": v.id, "version": v.version, "snapshot": v.snapshot, "created_at": v.created_at.isoformat()})


def rollback_agent(db: Session, agent_id: int, version_id: int) -> Agent:
    """用指定版本快照覆盖当前配置（版本号同样 +1）；快照缺失的字段保留现值兜底。"""
    a = get_agent(db, agent_id)
    av = db.get(AgentVersion, version_id)
    if av is None or av.agent_id != agent_id:
        # 版本必须存在且属于该智能体，防止拿别的智能体的版本覆盖
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
    # 回滚同样是一次配置变更，版本号继续递增，保证历史链不断
    a.version = (a.version or 0) + 1
    db.commit()
    db.refresh(a)
    return a
