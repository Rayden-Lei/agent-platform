"""工具（Tool）路由：工具的增删改查与连通性测试。

本模块仅允许 admin / developer 角色访问。
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.services import tool_service

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolIn(BaseModel):
    """工具配置请求体：type 默认 builtin（内置工具）；config 为工具参数；timeout 为调用超时（秒）。"""

    name: str
    description: str
    type: str = "builtin"
    config: dict = {}
    timeout: int = 30


class ToolTestIn(BaseModel):
    """工具测试请求体：args 为实际调用参数。"""

    args: dict = {}


@router.get("")
def list_tools(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """工具列表（分页），支持名称模糊匹配。"""
    return tool_service.list_tools(db, params, q)


@router.post("")
def create_tool(data: ToolIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建工具。"""
    return tool_service.create_tool(db, data)


@router.put("/{tool_id}")
def update_tool(tool_id: int, data: ToolIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 更新工具配置。"""
    return tool_service.update_tool(db, tool_id, data)


@router.delete("/{tool_id}")
def delete_tool(tool_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 删除工具。"""
    tool_service.delete_tool(db, tool_id)
    return {"code": 0, "message": "ok"}


@router.post("/{tool_id}/test")
async def test_tool(tool_id: int, data: ToolTestIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """测试工具：用给定参数实际调用一次并返回结果。"""
    result = await tool_service.test_tool(db, tool_id, data.args)
    return {"code": 0, "message": "ok", "data": {"result": result}}
