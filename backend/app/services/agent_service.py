from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.core.prompt_render import render
from app.db.models import Agent, AgentVersion, PromptTemplate, User
from app.schemas import AgentIn


def _template_versions(db: Session, agents: list[Agent]) -> dict[int, int]:
    """一次 IN 查询取这批智能体绑定模板的当前版本（禁止逐行查）。"""
    ids = {a.prompt_template_id for a in agents if a.prompt_template_id}
    if not ids:
        return {}
    rows = db.query(PromptTemplate.id, PromptTemplate.version).filter(PromptTemplate.id.in_(ids)).all()
    return {tid: version for tid, version in rows}


def _to_out(a: Agent, template_versions: dict[int, int]) -> dict:
    """智能体输出：附带 prompt_template_outdated（模板当前版本 > 绑定时版本）。"""
    current = template_versions.get(a.prompt_template_id) if a.prompt_template_id else None
    outdated = bool(current is not None and a.prompt_template_version is not None and current > a.prompt_template_version)
    return {
        "id": a.id, "name": a.name, "description": a.description, "system_prompt": a.system_prompt, "model_id": a.model_id,
        "params": a.params, "kb_ids": a.kb_ids, "tool_ids": a.tool_ids, "workflow_id": a.workflow_id,
        "status": a.status, "version": a.version,
        "prompt_template_id": a.prompt_template_id, "prompt_template_version": a.prompt_template_version,
        "prompt_variables": a.prompt_variables or {}, "prompt_template_outdated": outdated,
    }


def _single_out(db: Session, a: Agent) -> dict:
    return _to_out(a, _template_versions(db, [a]))


def _apply_prompt(db: Session, a: Agent, data: AgentIn) -> None:
    """system_prompt 与模板二选一（FR-028）。绑定模板：用模板当前版本 + prompt_variables 渲染写入 system_prompt，
    记下模板版本；缺必填变量 400。不绑定：行为与以前相同，三个模板字段清空。"""
    if data.prompt_template_id:
        if (data.system_prompt or "").strip():
            raise BizError(400, "绑定模板时不能同时手填 system_prompt")
        template = db.get(PromptTemplate, data.prompt_template_id)
        if template is None:
            raise BizError(404, "模板不存在")
        result = render(template.content, template.variables or [], data.prompt_variables)
        if result.missing:
            raise BizError(400, "缺少必填变量：" + ", ".join(result.missing))
        a.system_prompt = result.text
        a.prompt_template_id = template.id
        a.prompt_template_version = template.version
        a.prompt_variables = data.prompt_variables or {}
    else:
        a.system_prompt = data.system_prompt or ""
        a.prompt_template_id = None
        a.prompt_template_version = None
        a.prompt_variables = {}


def list_agents(db: Session, params: PageParams, q: str = None, status: str = None) -> dict:
    """分页列出智能体：q 对名称模糊匹配，status 精确过滤（如 published / draft）。
    outdated 标记用一次 IN 查询批量算，不逐行查模板。"""
    query = db.query(Agent)
    if q:
        query = query.filter(Agent.name.ilike(f"%{q}%"))
    if status:
        query = query.filter(Agent.status == status)
    page = paginate(query.order_by(Agent.id), params)
    versions = _template_versions(db, page["items"])
    page["items"] = [_to_out(a, versions) for a in page["items"]]
    return page


def create_agent(db: Session, data: AgentIn, user: User) -> dict:
    """新建智能体：初始为草稿态（draft），created_by 记录创建人。模板渲染失败（400）时不落库。"""
    a = Agent(
        name=data.name,
        description=data.description,
        model_id=data.model_id,
        params=data.params,
        kb_ids=data.kb_ids,
        tool_ids=data.tool_ids,
        workflow_id=data.workflow_id,
        created_by=user.id,
    )
    _apply_prompt(db, a, data)
    db.add(a)
    db.commit()
    db.refresh(a)
    return _single_out(db, a)


def get_agent(db: Session, agent_id: int) -> Agent:
    """按 ID 取智能体（ORM 对象，供服务内部与其他模块用），不存在抛 BizError(404)。"""
    a = db.get(Agent, agent_id)
    if a is None:
        raise BizError(404, "智能体不存在")
    return a


def get_agent_detail(db: Session, agent_id: int) -> dict:
    """详情（含 prompt_template_outdated）。"""
    return _single_out(db, get_agent(db, agent_id))


def update_agent(db: Session, agent_id: int, data: AgentIn) -> dict:
    """整表覆盖式更新（草稿态编辑），不校验发布状态。重新保存即按模板当前版本重新渲染，outdated 随之消除。"""
    a = get_agent(db, agent_id)
    a.name = data.name
    a.description = data.description
    a.model_id = data.model_id
    a.params = data.params
    a.kb_ids = data.kb_ids
    a.tool_ids = data.tool_ids
    a.workflow_id = data.workflow_id
    _apply_prompt(db, a, data)
    db.commit()
    db.refresh(a)
    return _single_out(db, a)


def delete_agent(db: Session, agent_id: int) -> None:
    """删除智能体，关联数据由数据库外键 CASCADE 级联删除。"""
    a = get_agent(db, agent_id)
    # agent_versions / conversations / messages / runs / run_nodes 由数据库外键 CASCADE 级联删除
    db.delete(a)
    db.commit()


def publish_agent(db: Session, agent_id: int, user: User) -> dict:
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
            "prompt_template_id": a.prompt_template_id,
            "prompt_template_version": a.prompt_template_version,
            "prompt_variables": a.prompt_variables or {},
        },
    ))
    db.commit()
    db.refresh(a)
    record_audit(db, user, "publish", "agent", a.id, detail={"name": a.name, "version": a.version})
    return _single_out(db, a)


def list_versions(db: Session, agent_id: int, params: PageParams) -> dict:
    """分页列出发布版本（按版本号倒序），先校验智能体存在。"""
    get_agent(db, agent_id)
    query = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc(), AgentVersion.id.desc())
    )
    return paginate(query, params, lambda v: {"id": v.id, "version": v.version, "snapshot": v.snapshot, "created_at": v.created_at.isoformat()})


def rollback_agent(db: Session, agent_id: int, version_id: int) -> dict:
    """用指定版本快照覆盖当前配置（版本号同样 +1）；快照缺失的字段保留现值兜底。

    模板三字段例外：绑定模板之前的快照没有这三个键，回滚到它就该恢复为"未绑定"，不能保留现值。
    """
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
    a.prompt_template_id = snap.get("prompt_template_id")
    a.prompt_template_version = snap.get("prompt_template_version")
    a.prompt_variables = snap.get("prompt_variables") or {}
    # 回滚同样是一次配置变更，版本号继续递增，保证历史链不断
    a.version = (a.version or 0) + 1
    db.commit()
    db.refresh(a)
    return _single_out(db, a)
