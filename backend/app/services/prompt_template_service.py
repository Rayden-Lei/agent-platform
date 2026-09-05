"""Prompt 模板服务（FR-028）：CRUD、版本快照、回滚、渲染预览。

版本语义与智能体一致：content / variables 变化才升版本并写快照；回滚也是一次新版本，历史不可篡改。
渲染是纯字符串替换（core/prompt_render），保存时就校验"内容引用的变量都已声明"。
"""
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.prompt_render import extract_variables, render
from app.db.models import Agent, PromptTemplate, PromptTemplateVersion, User


def _summary(t: PromptTemplate) -> dict:
    """列表项：不下发 content 大字段。"""
    return {
        "id": t.id, "name": t.name, "description": t.description, "variables": t.variables, "version": t.version,
        "created_by": t.created_by, "updated_at": t.updated_at.isoformat(),
    }


def _to_dict(t: PromptTemplate) -> dict:
    return {**_summary(t), "content": t.content, "created_at": t.created_at.isoformat(), "unused_variables": _unused(t.content, t.variables)}


def _unused(content: str, variables: list[dict]) -> list[str]:
    referenced = extract_variables(content)
    return [v["name"] for v in variables if v.get("name") not in referenced]


def _check_references(content: str, variables: list[dict]) -> None:
    """内容引用了未声明的变量 → 400（渲染时会原样留下占位符，必须在保存时拦住）。"""
    declared = {v.get("name") for v in variables}
    undeclared = sorted(extract_variables(content) - declared)
    if undeclared:
        raise BizError(400, "模板引用了未声明的变量：" + ", ".join(undeclared))


def _snapshot(db: Session, t: PromptTemplate, user: User | None) -> None:
    db.add(PromptTemplateVersion(template_id=t.id, version=t.version, content=t.content, variables=t.variables, created_by=user.id if user else None))


def _name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    query = db.query(PromptTemplate.id).filter(PromptTemplate.name == name)
    if exclude_id is not None:
        query = query.filter(PromptTemplate.id != exclude_id)
    return db.query(query.exists()).scalar()


SORTABLE = {"id": PromptTemplate.id, "name": PromptTemplate.name, "version": PromptTemplate.version, "updated_at": PromptTemplate.updated_at}


def list_templates(db: Session, params: PageParams, q: str | None = None, sort: SortParams | None = None) -> dict:
    """分页列出模板，q 对名称模糊匹配，白名单排序；列表不含 content，附绑定智能体数与创建人（各一次查询）。"""
    query = db.query(PromptTemplate)
    if q:
        query = query.filter(PromptTemplate.name.ilike(f"%{q}%"))
    page = paginate(apply_sort(query, sort, SORTABLE, [PromptTemplate.id.asc()]), params)
    rows = page["items"]
    ids = {t.id for t in rows}
    bound = dict(db.query(Agent.prompt_template_id, func.count(Agent.id)).filter(Agent.prompt_template_id.in_(ids)).group_by(Agent.prompt_template_id).all()) if ids else {}
    creator_ids = {t.created_by for t in rows if t.created_by}
    creators = dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
    page["items"] = [{**_summary(t), "agents_count": int(bound.get(t.id, 0)), "created_by_username": creators.get(t.created_by)} for t in rows]
    return page


def get_template_agents(db: Session, template_id: int) -> list[dict]:
    """绑定该模板的智能体清单（含是否落后于模板当前版本）。"""
    t = get_template(db, template_id)
    return [
        {"id": a.id, "name": a.name, "status": a.status, "prompt_template_version": a.prompt_template_version, "outdated": bool(a.prompt_template_version is not None and t.version > a.prompt_template_version)}
        for a in db.query(Agent).filter(Agent.prompt_template_id == template_id).order_by(Agent.id).all()
    ]


def get_template(db: Session, template_id: int) -> PromptTemplate:
    """按 ID 取模板，不存在抛 BizError(404)。"""
    t = db.get(PromptTemplate, template_id)
    if t is None:
        raise BizError(404, "模板不存在")
    return t


def get_template_detail(db: Session, template_id: int) -> dict:
    return _to_dict(get_template(db, template_id))


def create_template(db: Session, data, user: User) -> dict:
    """新建模板：版本 1 也写快照，回滚才能回到初版。重名 409（先查再靠唯一约束兜底并发）。"""
    variables = [v.model_dump() for v in data.variables]
    _check_references(data.content, variables)
    if _name_taken(db, data.name):
        raise BizError(409, "模板名称已存在")
    t = PromptTemplate(name=data.name, description=data.description, content=data.content, variables=variables, version=1, created_by=user.id)
    db.add(t)
    try:
        db.flush()
        _snapshot(db, t, user)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BizError(409, "模板名称已存在") from e
    db.refresh(t)
    record_audit(db, user, "create", "prompt_template", t.id, detail={"name": t.name})
    return _to_dict(t)


def update_template(db: Session, template_id: int, data, user: User) -> dict:
    """整体覆盖；content 或 variables 变化才 version + 1 并写快照，只改名称 / 描述不升版本。"""
    t = get_template(db, template_id)
    variables = [v.model_dump() for v in data.variables]
    _check_references(data.content, variables)
    if data.name != t.name and _name_taken(db, data.name, exclude_id=t.id):
        raise BizError(409, "模板名称已存在")
    changed = data.content != t.content or variables != (t.variables or [])
    t.name, t.description, t.content, t.variables = data.name, data.description, data.content, variables
    if changed:
        t.version = (t.version or 0) + 1
        _snapshot(db, t, user)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BizError(409, "模板名称已存在") from e
    db.refresh(t)
    return _to_dict(t)


def delete_template(db: Session, template_id: int, user: User) -> None:
    """删除模板，版本快照随外键 CASCADE 级联删除；仍被智能体绑定 → 409（解绑后可删）。"""
    t = get_template(db, template_id)
    bound = db.query(Agent).filter(Agent.prompt_template_id == template_id).count()
    if bound:
        raise BizError(409, f"仍有 {bound} 个智能体绑定该模板")
    name = t.name
    db.delete(t)
    db.commit()
    record_audit(db, user, "delete", "prompt_template", template_id, detail={"name": name})


def list_versions(db: Session, template_id: int, params: PageParams) -> dict:
    """分页列出版本快照，版本倒序。"""
    get_template(db, template_id)
    query = (
        db.query(PromptTemplateVersion)
        .filter(PromptTemplateVersion.template_id == template_id)
        .order_by(PromptTemplateVersion.version.desc(), PromptTemplateVersion.id.desc())
    )
    return paginate(query, params, lambda v: {"id": v.id, "version": v.version, "content": v.content, "variables": v.variables, "created_at": v.created_at.isoformat()})


def rollback_template(db: Session, template_id: int, version_id: int, user: User) -> dict:
    """用指定版本快照覆盖 content / variables，version + 1 并写新快照；版本必须属于该模板，否则 404。"""
    t = get_template(db, template_id)
    v = db.get(PromptTemplateVersion, version_id)
    if v is None or v.template_id != template_id:
        raise BizError(404, "版本不存在")
    t.content, t.variables = v.content, v.variables
    t.version = (t.version or 0) + 1
    _snapshot(db, t, user)
    db.commit()
    db.refresh(t)
    record_audit(db, user, "rollback", "prompt_template", t.id, detail={"from_version": v.version, "to_version": t.version})
    return _to_dict(t)


def render_template(db: Session, template_id: int, values: dict) -> dict:
    """渲染预览：缺必填变量 400，detail 列出缺失名。不调模型。"""
    t = get_template(db, template_id)
    result = render(t.content, t.variables or [], values)
    if result.missing:
        raise BizError(400, "缺少必填变量：" + ", ".join(result.missing))
    return {"content": result.text, "missing": [], "unused": result.unused}
