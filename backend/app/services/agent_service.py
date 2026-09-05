from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.prompt_render import render
from app.db.models import Agent, AgentVersion, KnowledgeBase, ModelConfig, PromptTemplate, Run, Tool, User, Workflow
from app.schemas import AgentIn

SORTABLE = {"id": Agent.id, "name": Agent.name, "status": Agent.status, "version": Agent.version, "updated_at": Agent.updated_at}


class _Related:
    """一页智能体的关联信息：模板版本、模型名、模板名、创建人、最近 7 天运行数与最近运行时间，各一次查询。"""

    def __init__(self, db: Session, agents: list[Agent]):
        ids = {a.id for a in agents}
        template_ids = {a.prompt_template_id for a in agents if a.prompt_template_id}
        model_ids = {a.model_id for a in agents if a.model_id}
        creator_ids = {a.created_by for a in agents if a.created_by}
        self.templates = {t.id: t for t in db.query(PromptTemplate).filter(PromptTemplate.id.in_(template_ids)).all()} if template_ids else {}
        self.models = dict(db.query(ModelConfig.id, ModelConfig.name).filter(ModelConfig.id.in_(model_ids)).all()) if model_ids else {}
        self.creators = dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
        since = datetime.now(timezone.utc) - timedelta(days=7)
        rows = db.query(Run.agent_id, func.count(Run.id), func.max(Run.started_at)).filter(Run.agent_id.in_(ids), Run.started_at >= since).group_by(Run.agent_id).all() if ids else []
        self.runs = {agent_id: (count, last) for agent_id, count, last in rows}

    def to_dict(self, a: Agent) -> dict:
        template = self.templates.get(a.prompt_template_id) if a.prompt_template_id else None
        current = template.version if template else None
        outdated = bool(current is not None and a.prompt_template_version is not None and current > a.prompt_template_version)
        runs_7d, last_run = self.runs.get(a.id, (0, None))
        return {
            "id": a.id, "name": a.name, "description": a.description, "system_prompt": a.system_prompt, "model_id": a.model_id,
            "params": a.params, "kb_ids": a.kb_ids, "tool_ids": a.tool_ids, "workflow_id": a.workflow_id,
            "status": a.status, "version": a.version,
            "prompt_template_id": a.prompt_template_id, "prompt_template_version": a.prompt_template_version,
            "prompt_variables": a.prompt_variables or {}, "prompt_template_outdated": outdated,
            "model_name": self.models.get(a.model_id), "prompt_template_name": template.name if template else None,
            "created_by": a.created_by, "created_by_username": self.creators.get(a.created_by),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            "runs_7d": int(runs_7d), "last_run_at": last_run.isoformat() if last_run else None,
        }


def _single_out(db: Session, a: Agent) -> dict:
    return _Related(db, [a]).to_dict(a)


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


def list_agents(db: Session, params: PageParams, q: str = None, status: str = None, model_id: int = None,
                kb_id: int = None, tool_id: int = None, prompt_template_id: int = None, sort: SortParams = None) -> dict:
    """分页列出智能体：q 名称模糊，status / model_id / prompt_template_id 精确，kb_id / tool_id 按 JSONB 数组包含过滤；
    白名单排序；关联信息批量装配，不逐行查库。"""
    query = db.query(Agent)
    if q:
        query = query.filter(Agent.name.ilike(f"%{q}%"))
    if status:
        query = query.filter(Agent.status == status)
    if model_id:
        query = query.filter(Agent.model_id == model_id)
    if prompt_template_id:
        query = query.filter(Agent.prompt_template_id == prompt_template_id)
    if kb_id:
        query = query.filter(Agent.kb_ids.contains([kb_id]))
    if tool_id:
        query = query.filter(Agent.tool_ids.contains([tool_id]))
    page = paginate(apply_sort(query, sort, SORTABLE, [Agent.id.asc()]), params)
    related = _Related(db, page["items"])
    page["items"] = [related.to_dict(a) for a in page["items"]]
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
    """详情：基础字段 + 关联对象（模型、工具、知识库、工作流、模板）与悬空引用清单。
    kb_ids / tool_ids 是 JSONB 数组无外键，知识库或工具删除后 ID 会残留，这里把查不到的 ID 显式列出。"""
    a = get_agent(db, agent_id)
    model = db.get(ModelConfig, a.model_id) if a.model_id else None
    tools = db.query(Tool).filter(Tool.id.in_(a.tool_ids)).order_by(Tool.id).all() if a.tool_ids else []
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(a.kb_ids)).order_by(KnowledgeBase.id).all() if a.kb_ids else []
    workflow = db.get(Workflow, a.workflow_id) if a.workflow_id else None
    template = db.get(PromptTemplate, a.prompt_template_id) if a.prompt_template_id else None
    found_tools, found_kbs = {t.id for t in tools}, {k.id for k in kbs}
    return {
        **_single_out(db, a),
        "model": {"id": model.id, "name": model.name, "provider": model.provider, "model_name": model.model_name, "is_enabled": model.is_enabled} if model else None,
        "tools": [{"id": t.id, "name": t.name, "type": t.type, "is_enabled": t.is_enabled} for t in tools],
        "missing_tool_ids": [i for i in (a.tool_ids or []) if i not in found_tools],
        "knowledge_bases": [{"id": k.id, "name": k.name, "is_public": k.is_public} for k in kbs],
        "missing_kb_ids": [i for i in (a.kb_ids or []) if i not in found_kbs],
        "workflow": {"id": workflow.id, "name": workflow.name, "status": workflow.status} if workflow else None,
        "prompt_template": {"id": template.id, "name": template.name, "version": template.version, "variables": template.variables} if template else None,
    }


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


def apply_batch_action(db: Session, agent_id: int, action: str, user: User) -> None:
    """批量操作的单条执行（publish / delete）。"""
    if action == "delete":
        delete_agent(db, agent_id)
    else:
        publish_agent(db, agent_id, user)


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
