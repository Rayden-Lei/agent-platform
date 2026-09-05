"""Prompt 模板路由（FR-028）：模板的增删改查、版本历史、回滚与渲染预览。

本模块仅允许 admin / developer 角色访问，不接受 API Key（管理接口）。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.core.prompt_render import VARIABLE_NAME_RE
from app.db.models import User
from app.db.session import get_db
from app.services import prompt_template_service

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])

MAX_VARIABLES = 30


class PromptVariable(BaseModel):
    """变量声明：name 是内容里 {{name}} 引用的名字；required 且无 default 的变量渲染时必须传值。"""

    name: str = Field(min_length=1, max_length=64, pattern=VARIABLE_NAME_RE.pattern)
    description: str = ""
    required: bool = False
    default: str | None = None


class PromptTemplateIn(BaseModel):
    """创建 / 更新请求体（整体覆盖）。变量最多 30 个且同名唯一，违反 422；内容引用未声明变量由服务层 400。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    content: str = Field(min_length=1)
    variables: list[PromptVariable] = Field(default_factory=list, max_length=MAX_VARIABLES)

    @field_validator("variables")
    @classmethod
    def _unique_names(cls, value: list[PromptVariable]) -> list[PromptVariable]:
        seen: set[str] = set()
        for v in value:
            if v.name in seen:
                raise ValueError(f"变量名重复：{v.name}")
            seen.add(v.name)
        return value


class PromptRenderIn(BaseModel):
    """渲染预览请求体：variables 为变量取值，未声明的键忽略。"""

    variables: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_templates(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """模板列表（分页，不含 content），支持名称模糊匹配。"""
    return prompt_template_service.list_templates(db, params, q)


@router.post("")
def create_template(data: PromptTemplateIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建模板；响应含 unused_variables（声明了但内容未使用）。409 重名；400 引用未声明变量。"""
    return prompt_template_service.create_template(db, data, user)


@router.get("/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """模板详情（含 content）。"""
    return prompt_template_service.get_template_detail(db, template_id)


@router.put("/{template_id}")
def update_template(template_id: int, data: PromptTemplateIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """整体覆盖更新；content / variables 变化时 version + 1 并写快照。"""
    return prompt_template_service.update_template(db, template_id, data, user)


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除模板（版本快照级联删除）。"""
    prompt_template_service.delete_template(db, template_id, user)
    return {"code": 0, "message": "ok"}


@router.get("/{template_id}/versions")
def list_versions(template_id: int, params: PageParams = Depends(page_params), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """版本历史（分页，版本倒序）。"""
    return prompt_template_service.list_versions(db, template_id, params)


@router.post("/{template_id}/rollback/{version_id}")
def rollback_template(template_id: int, version_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """回滚到指定版本：内容与变量恢复，version + 1；404 版本不属于该模板。"""
    return prompt_template_service.rollback_template(db, template_id, version_id, user)


@router.post("/{template_id}/render")
def render_template(template_id: int, data: PromptRenderIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """渲染预览：返回 {content, missing, unused}；缺必填变量 400。"""
    return prompt_template_service.render_template(db, template_id, data.variables)
