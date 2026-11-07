"""技能路由（docs/17 §4）：技能的增删改查与批量删除。

本模块仅允许 admin / developer 角色访问，不接受 API Key（管理接口）。
技能正文会进模型上下文，可能含内部地址与操作规则，与提示词模板同口径：写操作一律写审计，
分享访客拿不到正文（分享链路只按 skill_ids 装配，不暴露技能列表接口）。
"""
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.services import skill_import, skill_resource, skill_service
from app.services.skill_service import CONTENT_MAX_BYTES, DESCRIPTION_MAX, SKILL_NAME_MAX, SKILL_NAME_PATTERN

router = APIRouter(prefix="/skills", tags=["skills"])

MAX_RESOURCES = 20


class SkillIn(BaseModel):
    """创建 / 更新请求体（整体覆盖）。name 与 Agent Skills 开放标准一致：
    小写字母数字与连字符，不能以连字符开头/结尾、不能连续连字符 —— 它是模型调 load_skill 时唯一能传的标识。

    **不含 resources**：资源只由 /skills/{id}/resources 子接口增删（2026-11-06 改）。
    曾经放在这个整体覆盖体里，但资源条目带 object（对象存储键）与 size，前端回传时
    只要漏了 object，一次保存就把脚本从 MinIO 上摘成悬空引用 —— 收窄成单向入口后不会再发生。
    多传 resources 会 422（extra=forbid），而不是被静默忽略。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=SKILL_NAME_MAX, pattern=SKILL_NAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=DESCRIPTION_MAX)
    content: str = Field(min_length=1)
    always_on: bool = False
    is_enabled: bool = True


class SkillImportIn(BaseModel):
    """粘贴导入：SKILL.md 全文（含 frontmatter）。

    上限 128KB（正文上限 64KB 的两倍，给 frontmatter 与格式留余量）：
    没有上限时一段 100MB 的文本会让解析用的 DOTALL 正则与 splitlines 吃满 CPU 与内存 ——
    这个接口在鉴权之后、任何业务校验之前就有开销。
    """

    text: str = Field(min_length=1, max_length=128 * 1024)


class SkillBatchIn(BatchIn[Literal["delete"]]):
    """action 只接受 "delete"，其余值 422。"""


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """分块读并计数，超限 413。file.size 拿不到时（分块传输）也拦得住，不会先整块读进内存。"""
    buf = bytearray()
    while chunk := await file.read(256 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise BizError(413, f"单个资源最多 {limit // 1024}KB")
    return bytes(buf)


@router.get("")
def list_skills(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称或显示名模糊匹配"),
    always_on: bool | None = Query(None, description="只看常驻 / 只看按需"),
    is_enabled: bool | None = Query(None, description="只看启用 / 只看停用"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """技能列表（分页，不含 content），附绑定智能体数与创建人。"""
    return skill_service.list_skills(db, params, q, always_on, is_enabled, sort)


@router.get("/stats")
def skill_stats(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """技能总数与启用数（列表页头部用）。固定路径必须声明在 /{skill_id} 之前。"""
    return skill_service.stats(db)


@router.post("")
def create_skill(data: SkillIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建技能。409 重名；400 正文超过 64KB。"""
    return skill_service.create_skill(db, data, user)


@router.post("/batch")
def batch_skills(data: SkillBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量删除：逐条独立执行，仍被智能体绑定的技能 409 进失败清单。"""
    return run_batch(db, data.unique_ids(), lambda skill_id: skill_service.delete_skill(db, skill_id, user))


@router.post("/parse")
def parse_skill_md(data: SkillImportIn, user: User = Depends(require_roles("admin", "developer"))):
    """解析 SKILL.md（Agent Skills 开放标准）成技能字段，**不落库**。

    返回的字段直接填进编辑弹窗，使用者确认后走正常的 POST /skills 保存 ——
    导入与手填共用同一条校验路径，不存在"导入能绕过 name 格式 / 正文上限"的第二套入口。
    格式不对 400 并写明哪里不对（缺 frontmatter、缺 name / description、正文为空、不支持的 YAML 结构）。
    """
    try:
        parsed = skill_import.parse_skill_md(data.text)
    except skill_import.SkillImportError as e:
        raise BizError(400, str(e)) from e
    size = len(parsed["content"].encode("utf-8"))
    if size > CONTENT_MAX_BYTES:
        raise BizError(400, f"技能正文最多 {CONTENT_MAX_BYTES // 1024}KB，这个文件解析出 {size / 1024:.1f}KB，先拆成多个技能")
    return parsed


@router.get("/{skill_id}/preview")
def preview_skill(skill_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """预览这个技能**实际对模型长什么样**（纯本地拼装，不调模型、不花 token）。

    技能最容易写错的两处是 description（决定模型会不会想到用它）和 always_on（正文每轮
    都进上下文）。这两点在编辑框里看不出来，以往的反馈回路是"绑到智能体上跑一轮"——
    这个接口把那一步省掉，直接在技能页告诉使用者：哪一行会进提示词、多少 token、有什么坑。
    """
    return skill_service.preview_for_model(db, skill_id)


@router.get("/{skill_id}/resources")
def list_resources(skill_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """技能的资源清单：文件型的补实际大小，对象被外部删掉时标 missing。"""
    return skill_resource.list_resources(db, skill_id)


@router.post("/{skill_id}/resources")
async def upload_resource(
    skill_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """上传一个资源文件（脚本等）进对象存储，并登记到该技能的 resources。

    首版只收 .py（沙箱按 python 起进程，别的语言需要另一套加固）。单个上限 512KB。
    MinIO 写入是阻塞 IO，放线程池执行，不占事件循环（与知识库上传同一处理）。
    """
    name = (file.filename or "").strip()
    if not name:
        raise BizError(400, "文件名不能为空")
    if not name.endswith(skill_resource.SCRIPT_SUFFIXES):
        raise BizError(400, f"首版只支持 {' / '.join(skill_resource.SCRIPT_SUFFIXES)} 资源")
    content = await _read_limited(file, skill_resource.RESOURCE_MAX_BYTES)
    skill = skill_service.get_skill(db, skill_id)
    # 上限在这里也要判：SkillIn 不再收 resources，这条是唯一的写入入口，
    # 不判就等于"建技能时最多 20 个"形同虚设
    # 比对时按服务端规范化后的名字（store_file 会 strip），否则「带空格的新名字」会绕过上限
    existing = skill.resources or []
    if len(existing) >= MAX_RESOURCES and all(r.get("name") != name.strip() for r in existing):
        raise BizError(400, f"单个技能最多 {MAX_RESOURCES} 个资源")
    entry = await run_in_threadpool(skill_resource.store_file, skill_id, name, content, file.content_type or "text/plain")
    # 同名资源覆盖：先摘掉旧的，再追加新的（skills.resources 是整体 JSON，顺序即展示顺序）
    resources = [r for r in existing if r.get("name") != entry["name"]]
    resources.append(entry)
    skill.resources = resources
    db.commit()
    record_audit(db, user, "update", "skill", skill.id, detail={"name": skill.name, "resource": entry["name"], "size": entry["size"]})
    return entry


# name 用 :path —— 资源名允许单层目录（scripts/add.py），普通路径参数遇到 / 直接 404
@router.delete("/{skill_id}/resources/{name:path}")
def delete_resource(skill_id: int, name: str, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删一个资源：从 resources 摘掉并删除对象存储里的文件。"""
    skill = skill_service.get_skill(db, skill_id)
    target = next((r for r in (skill.resources or []) if r.get("name") == name), None)
    if target is None:
        raise BizError(404, "资源不存在")
    if target.get("object"):
        skill_resource.drop_file(target["object"])
    skill.resources = [r for r in (skill.resources or []) if r.get("name") != name]
    db.commit()
    record_audit(db, user, "update", "skill", skill.id, detail={"name": skill.name, "removed_resource": name})
    return {"code": 0, "message": "ok"}


@router.get("/{skill_id}")
def get_skill(skill_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """技能详情（含 content）。"""
    return skill_service.get_skill_detail(db, skill_id)


@router.put("/{skill_id}")
def update_skill(skill_id: int, data: SkillIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """整体覆盖；name / description / content 变化时 version + 1。改完立刻对线上生效（技能不进发布快照）。"""
    return skill_service.update_skill(db, skill_id, data, user)


@router.delete("/{skill_id}")
def delete_skill(skill_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除技能；仍被智能体绑定 409。"""
    skill_service.delete_skill(db, skill_id, user)
    return {"code": 0, "message": "ok"}
