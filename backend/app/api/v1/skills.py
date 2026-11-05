"""技能路由（docs/17 §4）：技能的增删改查与批量删除。

本模块仅允许 admin / developer 角色访问，不接受 API Key（管理接口）。
技能正文会进模型上下文，可能含内部地址与操作规则，与提示词模板同口径：写操作一律写审计，
分享访客拿不到正文（分享链路只按 skill_ids 装配，不暴露技能列表接口）。
"""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.services import skill_service
from app.services.skill_service import DESCRIPTION_MAX, SKILL_NAME_MAX, SKILL_NAME_PATTERN

router = APIRouter(prefix="/skills", tags=["skills"])

MAX_RESOURCES = 20


class SkillResource(BaseModel):
    """技能附带资源（首版只存文本）：name 是展示名，content 是正文。

    文件型资源（scripts / references 里的真文件）走 MinIO，等 P2.6 接沙箱时再加，
    现在留 type 字段是为了那时不用改结构。
    """

    name: str = Field(min_length=1, max_length=128)
    type: str = Field("text", max_length=32)
    content: str = Field("", max_length=20000)


class SkillIn(BaseModel):
    """创建 / 更新请求体（整体覆盖）。name 与 Agent Skills 开放标准一致：
    小写字母数字与连字符，不能以连字符开头/结尾、不能连续连字符 —— 它是模型调 load_skill 时唯一能传的标识。
    """

    name: str = Field(min_length=1, max_length=SKILL_NAME_MAX, pattern=SKILL_NAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=DESCRIPTION_MAX)
    content: str = Field(min_length=1)
    resources: list[SkillResource] = Field(default_factory=list, max_length=MAX_RESOURCES)
    always_on: bool = False
    is_enabled: bool = True

    @field_validator("resources")
    @classmethod
    def _unique_resource_names(cls, value: list[SkillResource]) -> list[SkillResource]:
        seen: set[str] = set()
        for r in value:
            if r.name in seen:
                raise ValueError(f"资源名重复：{r.name}")
            seen.add(r.name)
        return value


class SkillBatchIn(BatchIn[Literal["delete"]]):
    """action 只接受 "delete"，其余值 422。"""


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
