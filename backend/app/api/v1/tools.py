"""工具（Tool）路由：工具的增删改查、启停、批量操作与连通性测试。

本模块仅允许 admin / developer 角色访问。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.services import tool_service
from app.tools.schema import ToolParameters, format_validation_error

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolAuth(BaseModel):
    """鉴权方式（docs/15 RS-06）：api_key 要给位置（header / query）与参数名；bearer / basic 固定走 Authorization 头
    （basic 的凭据写成"用户名:密码"）。凭据本身不在这里，走 ToolIn.secret。"""

    model_config = ConfigDict(extra="forbid")
    type: Literal["none", "api_key", "bearer", "basic"] = "none"
    location: Literal["header", "query"] | None = None
    name: str | None = Field(None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _api_key_needs_place(self):
        if self.type == "api_key" and not (self.location and self.name):
            raise ValueError("api_key 鉴权要指定位置（header / query）与参数名")
        return self

    def stored(self) -> dict:
        """落库的形态：只留该方式用得到的键。"""
        if self.type == "api_key":
            return {"type": self.type, "location": self.location, "name": self.name}
        return {"type": self.type}


class ToolIn(BaseModel):
    """工具配置请求体：type 默认 builtin（内置工具）；config 为工具参数；timeout 为调用超时（秒）。

    config.parameters（HTTP 工具的参数声明，FR-030）在这里按 JSON Schema 子集校验并规范化，不合法 422。
    凭据走 auth + secret（加密托管，任何接口不回传）：secret 不传表示沿用已有凭据，clear_secret 为真清除；
    config.headers 里出现疑似凭据的键 422（2026-09-29 起，此前请求头里的 Token 原样存、原样返回）。
    """

    name: str
    description: str
    type: str = "builtin"
    config: dict = Field(default_factory=dict)
    timeout: int = 30
    auth: ToolAuth = Field(default_factory=ToolAuth)
    secret: str | None = Field(None, max_length=4096)
    clear_secret: bool = False

    @field_validator("config")
    @classmethod
    def _check_parameters(cls, config: dict) -> dict:
        leaked = tool_service.secret_header_keys(config.get("headers"))
        if leaked:
            raise ValueError(f"请在鉴权里配置凭据，不要写进请求头：{', '.join(leaked)}")
        if "parameters" not in config:
            return config
        try:
            parameters = ToolParameters.model_validate(config["parameters"])
        except ValidationError as e:
            raise ValueError(f"config.parameters 不合法：{format_validation_error(e)}") from e
        # 落库前规范化：补齐 type / required，去掉 enum: null，前端与引擎拿到的结构固定
        return {**config, "parameters": parameters.model_dump(exclude_none=True)}


class ToolTestIn(BaseModel):
    """工具测试请求体：args 为实际调用参数。"""

    args: dict = {}


class ToolBatchIn(BatchIn):
    action: Literal["enable", "disable", "delete"]


@router.get("")
def list_tools(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    type: Literal["builtin", "http"] | None = Query(None),
    is_enabled: bool | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """工具列表（分页），支持名称模糊、类型、启用状态过滤；sort 可选 id / name / type / timeout；附引用智能体数。"""
    return tool_service.list_tools(db, params, q, type, is_enabled, sort)


@router.post("")
def create_tool(data: ToolIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建工具。"""
    return tool_service.create_tool(db, data, user)


# 固定路径必须声明在 /{tool_id} 之前
@router.post("/batch")
def batch_tools(data: ToolBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量启用 / 停用 / 删除：逐条独立执行并返回成功与失败清单。"""
    return run_batch(db, data.unique_ids(), lambda tool_id: tool_service.apply_batch_action(db, tool_id, data.action, user))


@router.get("/{tool_id}")
def get_tool(tool_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """工具详情（含引用它的智能体清单）。"""
    return tool_service.get_tool_detail(db, tool_id)


@router.put("/{tool_id}")
def update_tool(tool_id: int, data: ToolIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 更新工具配置。"""
    return tool_service.update_tool(db, tool_id, data, user)


@router.post("/{tool_id}/toggle")
def toggle_tool(tool_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """启用 / 停用工具（开关切换）。停用后不再暴露给模型，工作流 tool 节点调用它会失败。"""
    current = tool_service.get_tool(db, tool_id)
    return tool_service.set_tool_enabled(db, tool_id, not current.is_enabled, user)


@router.delete("/{tool_id}")
def delete_tool(tool_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 删除工具。"""
    tool_service.delete_tool(db, tool_id, user)
    return {"code": 0, "message": "ok"}


@router.post("/{tool_id}/test")
async def test_tool(tool_id: int, data: ToolTestIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """测试工具：用给定参数实际调用一次并返回结果。"""
    result = await tool_service.test_tool(db, tool_id, data.args)
    return {"code": 0, "message": "ok", "data": {"result": result}}
