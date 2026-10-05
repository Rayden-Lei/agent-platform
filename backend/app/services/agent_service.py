from datetime import datetime, timedelta, timezone

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.prompt_render import render
from app.db.models import Agent, AgentVersion, KnowledgeBase, ModelConfig, PromptTemplate, Run, Tool, User, Workflow
from app.runtime.agent_config import SNAPSHOT_FIELDS, normalize_snapshot, resolve_live_config, snapshot_of
from app.schemas import AgentIn, AgentUpdateIn
from app.services import kb_service, run_service

SORTABLE = {"id": Agent.id, "name": Agent.name, "status": Agent.status, "version": Agent.version, "updated_at": Agent.updated_at}


class _Related:
    """一页智能体的关联信息：模板版本、模型名、模板名、创建人、线上快照、最近 7 天运行数与最近运行时间，各一次查询。"""

    def __init__(self, db: Session, agents: list[Agent]):
        ids = {a.id for a in agents}
        template_ids = {a.prompt_template_id for a in agents if a.prompt_template_id}
        model_ids = {a.model_id for a in agents if a.model_id}
        creator_ids = {a.created_by for a in agents if a.created_by}
        live_pairs = [(a.id, a.published_version) for a in agents if a.published_version is not None]
        self.templates = {t.id: t for t in db.query(PromptTemplate).filter(PromptTemplate.id.in_(template_ids)).all()} if template_ids else {}
        self.models = dict(db.query(ModelConfig.id, ModelConfig.name).filter(ModelConfig.id.in_(model_ids)).all()) if model_ids else {}
        self.creators = dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
        # 线上快照：判断"有未发布修改"要拿草稿与它比，一页一次 IN 查询
        self.live = {v.agent_id: normalize_snapshot(v.snapshot) for v in db.query(AgentVersion).filter(tuple_(AgentVersion.agent_id, AgentVersion.version).in_(live_pairs))} if live_pairs else {}
        since = datetime.now(timezone.utc) - timedelta(days=7)
        # 近 7 天运行不计装配页调试（docs/15 D-05）：运营指标看的是真实使用
        rows = db.query(Run.agent_id, func.count(Run.id), func.max(Run.started_at)).filter(
            Run.agent_id.in_(ids), Run.started_at >= since, run_service.operational_only(),
        ).group_by(Run.agent_id).all() if ids else []
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
            "published_version": a.published_version,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "has_unpublished_changes": a.published_version is not None and snapshot_of(a) != self.live.get(a.id),
        }


def _single_out(db: Session, a: Agent) -> dict:
    return _Related(db, [a]).to_dict(a)


def _prompt_fields(db: Session, data: AgentIn) -> dict:
    """system_prompt 与模板二选一（FR-028），算出提示词四个字段，不写库（保存与调试共用）。绑定模板：用模板当前版本 +
    prompt_variables 渲染成 system_prompt，记下模板版本；缺必填变量 400。不绑定：三个模板字段为空。"""
    if data.prompt_template_id:
        if (data.system_prompt or "").strip():
            raise BizError(400, "绑定模板时不能同时手填 system_prompt")
        template = db.get(PromptTemplate, data.prompt_template_id)
        if template is None:
            raise BizError(404, "模板不存在")
        result = render(template.content, template.variables or [], data.prompt_variables)
        if result.missing:
            raise BizError(400, "缺少必填变量：" + ", ".join(result.missing))
        return {"system_prompt": result.text, "prompt_template_id": template.id, "prompt_template_version": template.version,
                "prompt_variables": data.prompt_variables or {}}
    return {"system_prompt": data.system_prompt or "", "prompt_template_id": None, "prompt_template_version": None, "prompt_variables": {}}


def _apply_prompt(db: Session, a: Agent, data: AgentIn) -> None:
    for field, value in _prompt_fields(db, data).items():
        setattr(a, field, value)


def inline_snapshot(db: Session, data: AgentIn) -> dict:
    """装配页调试的内联配置（编辑器当前内容，含未保存修改）→ 与 snapshot_of 同形的快照。
    校验与保存同一口径（引用 404 / 400、模板渲染），不写 agents 行（docs/15 3.4）。"""
    validate_agent_config(db, data.model_id, data.tool_ids, data.kb_ids)
    return {"name": data.name, "description": data.description, "model_id": data.model_id, "params": data.params.to_dict(),
            "kb_ids": data.kb_ids, "tool_ids": data.tool_ids, "workflow_id": data.workflow_id, **_prompt_fields(db, data)}


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
        # 与模型页的引用数同一口径：草稿已换模型、线上还在用这个模型的也列出来（模型列上显示的是草稿的模型）
        query = query.filter(Agent.id.in_(agent_ids_using_models(db, {model_id})[model_id]))
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


def agent_ids_using_models(db: Session, model_ids: set) -> dict[int, set]:
    """每个模型被哪些智能体用着：草稿引用它，或在线智能体的线上版本引用它（docs/15 3.2，2026-09-25 起）。
    模型页的引用数与清单、删除模型的引用检查、智能体列表按模型筛选共用这一个口径：停用与删除模型影响的是线上版本，
    只数草稿会显示"没人用"、删除却让线上悬空。已下线的与历史版本不算，重新上线或回滚上线到那一版时发布校验会拦下。各一次查询。"""
    refs: dict[int, set] = {mid: set() for mid in model_ids}
    if not model_ids:
        return refs
    for agent_id, model_id in db.query(Agent.id, Agent.model_id).filter(Agent.model_id.in_(model_ids)):
        refs[model_id].add(agent_id)
    live_model_id = AgentVersion.snapshot["model_id"].astext
    live = (
        db.query(Agent.id, live_model_id)
        .join(AgentVersion, (AgentVersion.agent_id == Agent.id) & (AgentVersion.version == Agent.published_version))
        .filter(Agent.status == "published", live_model_id.in_([str(i) for i in model_ids]))
    )
    for agent_id, model_id in live:
        refs[int(model_id)].add(agent_id)
    return refs


def list_available_agents(db: Session, params: PageParams, q: str = None) -> dict:
    """可对话的智能体：只列已发布且有线上版本的，名称与描述取线上快照（草稿改名不影响对外展示），
    q 按线上名称模糊，按 id 升序（与对话页原来的默认选中口径一致）。字段白名单由路由的 AgentBriefOut 保证。"""
    query = (
        db.query(Agent.id, Agent.published_at, AgentVersion.snapshot)
        .join(AgentVersion, (AgentVersion.agent_id == Agent.id) & (AgentVersion.version == Agent.published_version))
        .filter(Agent.status == "published")
    )
    if q:
        query = query.filter(AgentVersion.snapshot["name"].astext.ilike(f"%{q}%"))
    return paginate(query.order_by(Agent.id.asc()), params, lambda r: {
        "id": r.id, "name": (r.snapshot or {}).get("name"), "description": (r.snapshot or {}).get("description"), "published_at": r.published_at,
    })


def get_available_agent(db: Session, agent_id: int) -> dict:
    """单个可对话智能体（与列表同一口径）：名称与描述取线上快照；不存在 404、未发布 403「智能体未发布」、已下线 403「智能体已下线」。"""
    live = resolve_live_config(db, agent_id)
    return {"id": agent_id, "name": live.name, "description": live.description, "published_at": db.get(Agent, agent_id).published_at}


def _check_ids(db: Session, model_cls, ids: list, label: str) -> None:
    if not ids:
        return
    found = {i for (i,) in db.query(model_cls.id).filter(model_cls.id.in_(ids))}
    missing = [i for i in ids if i not in found]
    if missing:
        raise BizError(400, f"{label}不存在：{', '.join(str(i) for i in missing)}")


def validate_agent_config(db: Session, model_id: int, tool_ids: list, kb_ids: list) -> None:
    """保存、发布、回滚上线共用的引用校验（docs/15 3.3）：模型须存在（404「模型不存在」）且启用（400「模型已停用」）；
    工具、知识库须存在（400 并列出缺失 ID）。结构与长度由 AgentIn 管（422）。
    2026-09-25 前不校验：不存在的 model_id 撞外键走通用 500，不存在的工具与知识库 ID 悄悄存进去。"""
    model = db.get(ModelConfig, model_id)
    if model is None:
        raise BizError(404, "模型不存在")
    if not model.is_enabled:
        raise BizError(400, "模型已停用")
    _check_ids(db, Tool, tool_ids, "工具")
    _check_ids(db, KnowledgeBase, kb_ids, "知识库")


def _check_new_kbs_visible(db: Session, kb_ids: list, existing: list, role: str) -> None:
    """这次新增绑定的知识库须对保存人可见（docs/15 3.3、KB-01）：不可见与不存在同一句提示，不暴露受限库是否存在。
    已有绑定不追溯 —— admin 绑上的受限库，developer 只改提示词照样能保存；对话检索按访问者身份过滤，绑定本身不泄露内容。"""
    kept = set(existing or [])
    added = [i for i in kb_ids if i not in kept]
    if not added:
        return
    visible = {i for (i,) in db.query(KnowledgeBase.id).filter(KnowledgeBase.id.in_(added), kb_service.visible_kb_filter(role))}
    hidden = [i for i in added if i not in visible]
    if hidden:
        raise BizError(400, f"知识库不存在：{', '.join(str(i) for i in hidden)}")


def create_agent(db: Session, data: AgentIn, user: User) -> dict:
    """新建智能体：初始为草稿态（draft），created_by 记录创建人。引用校验或模板渲染失败时不落库。"""
    validate_agent_config(db, data.model_id, data.tool_ids, data.kb_ids)
    _check_new_kbs_visible(db, data.kb_ids, [], user.role)
    a = Agent(
        name=data.name,
        description=data.description,
        model_id=data.model_id,
        params=data.params.to_dict(),
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
    kb_ids / tool_ids 是 JSONB 数组无外键，知识库或工具删除后 ID 会残留，这里把查不到的 ID 显式列出。
    另给草稿与线上两份同形快照（snapshot_of 定义字段）：发布弹窗、版本对比按它们做字段级差异，前端不再自己维护字段清单。"""
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
        "draft_snapshot": snapshot_of(a),
        "live_snapshot": _live_snapshot(db, a),
    }


def update_agent(db: Session, agent_id: int, data: AgentUpdateIn, user: User) -> dict:
    """整体覆盖草稿（发布语义下只改草稿，对外入口仍按线上版本回答，发布后才生效）。

    expected_updated_at 与库中不一致 409：两个人同时编辑时后保存的人不会悄悄覆盖前一个人的修改（docs/15 D-11）。
    重新保存即按模板当前版本重新渲染，outdated 随之消除。写审计 update，detail 只记改了哪些字段。
    """
    a = get_agent(db, agent_id)
    if a.updated_at != data.expected_updated_at:
        raise BizError(409, "已被他人修改，请刷新后再改")
    validate_agent_config(db, data.model_id, data.tool_ids, data.kb_ids)
    _check_new_kbs_visible(db, data.kb_ids, a.kb_ids, user.role)
    before = snapshot_of(a)
    a.name = data.name
    a.description = data.description
    a.model_id = data.model_id
    a.params = data.params.to_dict()
    a.kb_ids = data.kb_ids
    a.tool_ids = data.tool_ids
    a.workflow_id = data.workflow_id
    _apply_prompt(db, a, data)
    db.commit()
    db.refresh(a)
    changed = [field for field, value in snapshot_of(a).items() if before[field] != value]
    if changed:
        record_audit(db, user, "update", "agent", a.id, detail={"name": a.name, "changed": changed})
    return _single_out(db, a)


def delete_agent(db: Session, agent_id: int) -> None:
    """删除智能体，关联数据由数据库外键 CASCADE 级联删除。"""
    a = get_agent(db, agent_id)
    # agent_versions / conversations / messages / runs / run_nodes 由数据库外键 CASCADE 级联删除
    db.delete(a)
    db.commit()


def _lock_agent(db: Session, agent_id: int) -> Agent:
    """SELECT … FOR UPDATE 锁住智能体行：发布与回滚上线要"读线上 → 比较 → 生成版本号"一气呵成，
    并发的第二个请求等锁，拿到锁后看到的已是新的线上版本（此前先读后写，并发发布会写出重复版本号）。"""
    a = db.query(Agent).filter(Agent.id == agent_id).with_for_update().populate_existing().one_or_none()
    if a is None:
        raise BizError(404, "智能体不存在")
    return a


def _live_snapshot(db: Session, a: Agent) -> dict | None:
    if a.published_version is None:
        return None
    av = db.query(AgentVersion).filter(AgentVersion.agent_id == a.id, AgentVersion.version == a.published_version).one_or_none()
    return normalize_snapshot(av.snapshot) if av else None


def _go_live(db: Session, a: Agent, snapshot: dict, user: User, note: str | None) -> str:
    """让 snapshot 成为线上配置并返回 publish_result。与线上一致时不生成版本：已上线的返回 unchanged（幂等），
    已下线的原样重新上线；否则生成新版本。版本号：从没有快照的从 v1 起（新建草稿的 agents.version 默认 1 不是发出过的号）；
    有快照的取"最大快照号与 agents.version 的较大者 + 1"，早期回滚只加过 agents.version，不能复用界面上出现过的号。"""
    if _live_snapshot(db, a) == snapshot:
        if a.status == "published":
            return "unchanged"
        a.status = "published"
        return "published"
    latest = db.query(func.max(AgentVersion.version)).filter(AgentVersion.agent_id == a.id).scalar()
    version = max(latest, a.version or 0) + 1 if latest else 1
    db.add(AgentVersion(agent_id=a.id, version=version, snapshot=snapshot, created_by=user.id, note=note))
    a.version = version
    a.published_version = version
    a.published_at = datetime.now(timezone.utc)
    a.status = "published"
    return "published"


def publish_agent(db: Session, agent_id: int, user: User, note: str | None = None) -> dict:
    """发布草稿：草稿成为新的线上版本（docs/15 3.2，FR-039）。发布前校验引用（模型停用 400 等），不通过不生成版本。
    草稿与线上一致时返回 unchanged 不生成版本；已下线的原样发布即重新上线。"""
    a = _lock_agent(db, agent_id)
    validate_agent_config(db, a.model_id, a.tool_ids or [], a.kb_ids or [])
    result = _go_live(db, a, snapshot_of(a), user, note)
    db.commit()
    db.refresh(a)
    if result == "published":
        record_audit(db, user, "publish", "agent", a.id, detail={"name": a.name, "version": a.published_version, "note": note})
    return {**_single_out(db, a), "publish_result": result}


def _get_version(db: Session, agent_id: int, version_id: int) -> AgentVersion:
    av = db.get(AgentVersion, version_id)
    if av is None or av.agent_id != agent_id:
        # 版本必须存在且属于该智能体，防止拿别的智能体的版本覆盖
        raise BizError(404, "版本不存在")
    return av


def restore_version(db: Session, agent_id: int, version_id: int, user: User) -> dict:
    """恢复到草稿：草稿 = 该版本快照，线上不变（docs/15 D-04）。只校验模型存在（外键）：
    工具或知识库后来被删了也允许恢复，悬空引用由详情页提示、发布时再拦，否则删掉一个知识库会让所有旧版本都恢复不了。"""
    a = get_agent(db, agent_id)
    av = _get_version(db, agent_id, version_id)
    snap = normalize_snapshot(av.snapshot)
    if db.get(ModelConfig, snap["model_id"]) is None:
        raise BizError(404, "模型不存在")
    for field in SNAPSHOT_FIELDS:
        setattr(a, field, snap[field])
    db.commit()
    db.refresh(a)
    record_audit(db, user, "restore", "agent", a.id, detail={"name": a.name, "version": av.version})
    return _single_out(db, a)


def rollback_agent(db: Session, agent_id: int, version_id: int, user: User) -> dict:
    """回滚上线：用该版本快照生成一个新版本并置为线上，草稿不动（docs/15 D-04；2026-09-25 前是覆盖草稿行、立即生效）。
    线上出事时一键止血，又不丢掉正在改的草稿。与线上一致时 unchanged（双击不会连出两个版本）。"""
    a = _lock_agent(db, agent_id)
    av = _get_version(db, agent_id, version_id)
    snap = normalize_snapshot(av.snapshot)
    validate_agent_config(db, snap["model_id"], snap["tool_ids"], snap["kb_ids"])
    result = _go_live(db, a, snap, user, f"回滚到 v{av.version}")
    db.commit()
    db.refresh(a)
    if result == "published":
        record_audit(db, user, "rollback", "agent", a.id, detail={"name": a.name, "from_version": av.version, "version": a.published_version})
    return {**_single_out(db, a), "publish_result": result}


def offline_agent(db: Session, agent_id: int, user: User) -> dict:
    """下线：对外入口一律 403「智能体已下线」，线上版本保留，重新发布即恢复。已下线再下线 200（幂等）；从未发布过 400。"""
    a = get_agent(db, agent_id)
    if a.published_version is None:
        raise BizError(400, "智能体还没有发布过，无需下线")
    if a.status != "offline":
        a.status = "offline"
        db.commit()
        record_audit(db, user, "offline", "agent", a.id, detail={"name": a.name, "version": a.published_version})
    return {"id": a.id, "status": a.status}


def apply_batch_action(db: Session, agent_id: int, action: str, user: User) -> None:
    """批量操作的单条执行（publish / offline / delete）。"""
    if action == "delete":
        delete_agent(db, agent_id)
    elif action == "offline":
        offline_agent(db, agent_id, user)
    else:
        publish_agent(db, agent_id, user)


def list_versions(db: Session, agent_id: int, params: PageParams) -> dict:
    """分页列出发布版本（按版本号倒序）：附发布人、说明、是否线上，快照里的模型与模板解析成名称（一页各一次查询）。"""
    a = get_agent(db, agent_id)
    page = paginate(
        db.query(AgentVersion).filter(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc(), AgentVersion.id.desc()), params,
    )
    rows = page["items"]
    creator_ids = {v.created_by for v in rows if v.created_by}
    model_ids = {(v.snapshot or {}).get("model_id") for v in rows} - {None}
    template_ids = {(v.snapshot or {}).get("prompt_template_id") for v in rows} - {None}
    creators = dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
    models = dict(db.query(ModelConfig.id, ModelConfig.name).filter(ModelConfig.id.in_(model_ids)).all()) if model_ids else {}
    templates = dict(db.query(PromptTemplate.id, PromptTemplate.name).filter(PromptTemplate.id.in_(template_ids)).all()) if template_ids else {}
    page["items"] = [{
        # 快照补齐成与 snapshot_of 同形（早期版本没有模板三字段），与草稿对比时不会把"缺键"当成差异
        "id": v.id, "version": v.version, "snapshot": normalize_snapshot(v.snapshot), "created_at": v.created_at.isoformat(),
        "created_by": v.created_by, "created_by_username": creators.get(v.created_by), "note": v.note,
        "is_live": a.status == "published" and v.version == a.published_version,
        "model_name": models.get((v.snapshot or {}).get("model_id")),
        "prompt_template_name": templates.get((v.snapshot or {}).get("prompt_template_id")),
    } for v in rows]
    return page
