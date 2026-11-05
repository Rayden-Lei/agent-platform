"""技能服务（docs/17 §4）：CRUD 与 load_skill 的白名单查找。

技能是「操作手册」型知识，与提示词模板分工不同：模板是「人设」，保存时渲染进 system_prompt；
技能是「某类任务的额外知识」，运行时按需加载 —— 只把 name + description 放进提示词目录，
模型需要时调内置工具 load_skill(name) 取正文。

版本语义与提示词模板同口径：影响模型所见的字段（name / description / content）变化才 +1，
只改显示名、常驻开关不升版本。不保留历史快照 —— 技能没有发布流程，改完即对所有线上智能体生效。
"""
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.models import Agent, Skill, User
from app.db.session import rows_to_dict
from app.services import skill_resource

# 与 Agent Skills 开放标准（agentskills.io）一致：小写字母数字与连字符，不能以连字符开头/结尾、不能连续连字符。
# 收紧格式的理由不只是"好看"：name 是模型调 load_skill 时唯一能传的标识，带大写或空格会让它频繁传错。
SKILL_NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
SKILL_NAME_MAX = 64
# description 决定模型会不会调用这个技能，标准给的上限是 1024
DESCRIPTION_MAX = 1024
# 正文上限按字节算：一条技能正文会进模型上下文，不设上限时一条技能就能吃光窗口
CONTENT_MAX_BYTES = 64 * 1024
# 影响模型所见的字段：这些变化才升版本
MODEL_FACING = ("name", "description", "content")

SORTABLE = {"id": Skill.id, "name": Skill.name, "display_name": Skill.display_name, "version": Skill.version, "updated_at": Skill.updated_at}


def _summary(s: Skill) -> dict:
    """列表项：不下发 content 大字段。"""
    return {
        "id": s.id, "name": s.name, "display_name": s.display_name, "description": s.description,
        "always_on": s.always_on, "is_enabled": s.is_enabled, "version": s.version,
        "resources": s.resources or [], "created_by": s.created_by,
        "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat(),
    }


def _to_dict(s: Skill) -> dict:
    return {**_summary(s), "content": s.content}


def _check_name_taken(db: Session, name: str, exclude_id: int | None = None) -> None:
    """重名 409（先查再靠唯一约束兜底并发）。name 是模型查找技能的唯一键，重名会让它取错手册。"""
    query = db.query(Skill.id).filter(Skill.name == name)
    if exclude_id is not None:
        query = query.filter(Skill.id != exclude_id)
    if db.query(query.exists()).scalar():
        raise BizError(409, "技能名称已存在")


def _check_content_size(content: str) -> None:
    """正文按 UTF-8 字节数限 64KB：中文一个字 3 字节，按字符数限制会让中文技能超出一倍。"""
    size = len(content.encode("utf-8"))
    if size > CONTENT_MAX_BYTES:
        raise BizError(400, f"技能正文最多 {CONTENT_MAX_BYTES // 1024}KB，当前 {size / 1024:.1f}KB")


def bound_agent_count(db: Session, skill_id: int) -> int:
    """绑定该技能的智能体数。skill_ids 是 JSONB 数组无外键，只能扫非空的行后在内存里数；
    智能体数量是百级，比给 JSONB 建 GIN 索引更划算（docs/17 §4.3 选了 JSONB 而非关联表）。"""
    rows = db.query(Agent.id, Agent.skill_ids).filter(Agent.skill_ids != []).all()
    return sum(1 for _, ids in rows if skill_id in (ids or []))


def list_skills(db: Session, params: PageParams, q: str | None = None, always_on: bool | None = None,
                is_enabled: bool | None = None, sort: SortParams | None = None) -> dict:
    """分页列出技能，q 对 name / display_name 模糊匹配，白名单排序；列表不含 content，附绑定智能体数与创建人。"""
    query = db.query(Skill)
    if q:
        query = query.filter(Skill.name.ilike(f"%{q}%") | Skill.display_name.ilike(f"%{q}%"))
    if always_on is not None:
        query = query.filter(Skill.always_on.is_(always_on))
    if is_enabled is not None:
        query = query.filter(Skill.is_enabled.is_(is_enabled))
    page = paginate(apply_sort(query, sort, SORTABLE, [Skill.id.asc()]), params)
    rows = page["items"]
    creator_ids = {s.created_by for s in rows if s.created_by}
    creators = rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
    # 绑定数一次扫非空行算完，不逐行查库
    bindings: dict[int, int] = {}
    if rows:
        for _, ids in db.query(Agent.id, Agent.skill_ids).filter(Agent.skill_ids != []):
            for sid in ids or []:
                bindings[sid] = bindings.get(sid, 0) + 1
    page["items"] = [{**_summary(s), "agents_count": bindings.get(s.id, 0), "created_by_username": creators.get(s.created_by)} for s in rows]
    return page


def get_skill(db: Session, skill_id: int) -> Skill:
    """按 ID 取技能，不存在抛 BizError(404)。"""
    s = db.get(Skill, skill_id)
    if s is None:
        raise BizError(404, "技能不存在")
    return s


def get_skill_detail(db: Session, skill_id: int) -> dict:
    return {**_to_dict(get_skill(db, skill_id)), "agents_count": bound_agent_count(db, skill_id)}


def create_skill(db: Session, data, user: User) -> dict:
    """新建技能，版本从 1 起。重名 409；正文超 64KB 400。"""
    _check_content_size(data.content)
    _check_name_taken(db, data.name)
    s = Skill(
        name=data.name, display_name=data.display_name, description=data.description, content=data.content,
        resources=[r.model_dump() for r in data.resources], always_on=data.always_on, is_enabled=data.is_enabled,
        version=1, created_by=user.id,
    )
    db.add(s)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BizError(409, "技能名称已存在") from e
    db.refresh(s)
    record_audit(db, user, "create", "skill", s.id, detail={"name": s.name})
    return _to_dict(s)


def update_skill(db: Session, skill_id: int, data, user: User) -> dict:
    """整体覆盖；name / description / content 变化才 version + 1，只改显示名或开关不升版本。

    技能没有发布流程：改完立刻对所有绑定它的线上智能体生效（快照里只有 skill_ids，不含正文）。
    审计只记改了哪些字段，不记正文 —— 正文可能有几千字且含内部规则，进审计会撑爆日志。
    """
    s = get_skill(db, skill_id)
    _check_content_size(data.content)
    if data.name != s.name:
        _check_name_taken(db, data.name, exclude_id=s.id)
    before = {field: getattr(s, field) for field in MODEL_FACING}
    s.name, s.display_name, s.description, s.content = data.name, data.display_name, data.description, data.content
    s.resources = [r.model_dump() for r in data.resources]
    s.always_on, s.is_enabled = data.always_on, data.is_enabled
    changed = [field for field in MODEL_FACING if getattr(s, field) != before[field]]
    if changed:
        s.version = (s.version or 0) + 1
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BizError(409, "技能名称已存在") from e
    db.refresh(s)
    if changed:
        record_audit(db, user, "update", "skill", s.id, detail={"name": s.name, "changed": changed, "version": s.version})
    return _to_dict(s)


def delete_skill(db: Session, skill_id: int, user: User) -> None:
    """删除技能。仍被智能体绑定 → 409（解绑后可删）。

    skill_ids 是 JSONB 无外键，删了不会级联清理，会留下悬空 ID；所以这里显式拦，
    与提示词模板"仍被绑定 409"同一口径，让使用者先解绑再删。
    """
    s = get_skill(db, skill_id)
    bound = bound_agent_count(db, skill_id)
    if bound:
        raise BizError(409, f"仍有 {bound} 个智能体绑定该技能")
    name = s.name
    resources = list(s.resources or [])
    db.delete(s)
    db.commit()
    # 对象存储里的资源要显式清：库里删了行不会连带删 MinIO 对象，不清就是永久垃圾。
    # 放在 commit 之后：先保证库里删成功，再清对象；反过来若 commit 失败，对象已经没了但技能还在。
    skill_resource.drop_all(skill_id, resources)
    record_audit(db, user, "delete", "skill", skill_id, detail={"name": name})


def load_for_model(db: Session, skill_ids: list, name: str) -> Skill:
    """load_skill 工具的唯一入口：只允许读本次装配的 skill_ids 里的技能。

    白名单必须在这里判，不能只靠"模型应该只传目录里的名字"：工具参数是模型生成的，
    没有约束它可以传任意字符串，不判就等于给了一个读全库技能的越权入口（docs/17 §4.4 第 2 条）。

    未绑定 / 不存在 / 已停用返回同一句「技能不存在」，不区分原因 —— 区分了就等于告诉模型
    "这个技能存在但你不能看"，等于把技能清单泄露出去。
    """
    if not skill_ids:
        raise BizError(404, "技能不存在")
    s = db.query(Skill).filter(Skill.id.in_(skill_ids), Skill.name == name, Skill.is_enabled.is_(True)).one_or_none()
    if s is None:
        raise BizError(404, "技能不存在")
    return s


def enabled_skills(db: Session, skill_ids: list) -> list[Skill]:
    """装配用：取出启用的技能行，顺序按传入的 skill_ids（与装配页里的排列一致，目录稳定）。

    停用的技能不装配 —— 停用是"暂时不给模型用"，绑定关系保留，重新启用即恢复。
    """
    if not skill_ids:
        return []
    rows = db.query(Skill).filter(Skill.id.in_(skill_ids), Skill.is_enabled.is_(True)).all()
    by_id = {s.id: s for s in rows}
    return [by_id[i] for i in skill_ids if i in by_id]


def catalog_text(skills: list[Skill]) -> str:
    """「可用技能」目录：一行一个 name: description，告诉模型有哪些手册可查。

    只放 name 与 description（渐进式披露的第 1 层，约 100 token/个），正文等模型真要用时
    再调 load_skill 取 —— 绑十个技能也不会把上下文占满。
    """
    if not skills:
        return ""
    lines = "\n".join(f"- {s.name}：{s.description}" for s in skills)
    return (
        "【可用技能】以下是你可以在需要时加载的操作手册。"
        "遇到对应任务时先调 load_skill(name) 取正文，按里面的步骤做；不要凭记忆猜流程。\n" + lines
    )


def always_on_text(skills: list[Skill]) -> str:
    """常驻技能的正文：always_on 的技能每轮都要用到（如输出格式约定），直接拼进系统提示。"""
    bodies = [f"【技能 {s.name}】\n{s.content}" for s in skills if s.always_on]
    return "\n\n".join(bodies)


def stats(db: Session) -> dict:
    """技能总数与启用数，供列表页头部展示（一次查询）。"""
    total, enabled = db.query(func.count(Skill.id), func.count(Skill.id).filter(Skill.is_enabled.is_(True))).one()
    return {"total": int(total), "enabled": int(enabled)}
