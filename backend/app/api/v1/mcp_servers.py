"""MCP 连接器路由（docs/17 §5，P5）：登记外部 MCP server、同步工具、测试连接。

本模块仅允许 admin / developer 角色访问，不接受 API Key（管理接口）。
凭据与工具同一口径：加密存 secret_enc，任何接口都不回传明文，只回 has_secret。
"""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.services import mcp_service

router = APIRouter(prefix="/mcp-servers", tags=["mcp"])


class McpServerIn(BaseModel):
    """创建 / 更新请求体（整体覆盖）。

    凭据：secret 不传表示沿用已有凭据，clear_secret 为真清除（与工具同一口径）。
    allowed_hosts 必填 —— 与 HTTP 工具不同，这里不给"空名单放行"的口子：
    MCP 的地址是管理员配的外部地址，没写白名单就无从判断目标是否可信。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(None, max_length=1024)
    transport: Literal["http", "sse"] = "http"
    url: str = Field(min_length=1, max_length=512)
    headers: dict = Field(default_factory=dict)
    secret: str | None = Field(None, max_length=4096)
    clear_secret: bool = False
    is_enabled: bool = True
    allowed_hosts: list[str] = Field(default_factory=list)


class McpTestIn(McpServerIn):
    """测试连接：用请求体里的配置实际连一次，**不落库**（新建时还没保存也能测）。

    server_id 可选：编辑已有服务器且没重填凭据时，从这里找回已存的凭据。
    """

    server_id: int | None = None


class McpBatchIn(BatchIn[Literal["enable", "disable", "delete"]]):
    """action 只接受 "enable", "disable", "delete"，其余值 422。"""


@router.get("")
def list_servers(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称或描述模糊匹配"),
    is_enabled: bool | None = Query(None, description="只看启用 / 只看停用"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """服务器列表（分页），附已同步工具数与创建人。凭据只回 has_secret。"""
    return mcp_service.list_servers(db, params, q, is_enabled, sort)


@router.post("")
def create_server(data: McpServerIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建服务器。409 重名；400 地址非法 / 白名单为空 / 请求头里写了凭据。"""
    return mcp_service.create_server(db, data, user)


@router.post("/batch")
def batch_servers(data: McpBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量启用 / 停用 / 删除：逐条独立执行并返回成功与失败清单。"""
    def act(server_id: int) -> None:
        if data.action == "delete":
            mcp_service.delete_server(db, server_id, user)
        else:
            mcp_service.set_enabled(db, server_id, data.action == "enable", user)

    return run_batch(db, data.unique_ids(), act)


@router.post("/test")
async def test_connection(data: McpTestIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """测试连接（不落库）：连一次、取工具清单、返回条数与名字。固定路径必须声明在 /{server_id} 之前。"""
    return await mcp_service.test_connection(db, data)


@router.get("/{server_id}")
def get_server(server_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """服务器详情：附它同步出来的工具清单。"""
    return mcp_service.get_detail(db, server_id)


@router.put("/{server_id}")
def update_server(server_id: int, data: McpServerIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """整体覆盖；凭据不传沿用、传了更换、clear_secret 清除。"""
    return mcp_service.update_server(db, server_id, data, user)


@router.post("/{server_id}/toggle")
def toggle_server(server_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """启用 / 停用。停用会同时停用它同步出来的全部工具（地址与凭据都在服务器行上）。"""
    current = mcp_service.get_server(db, server_id)
    return mcp_service.set_enabled(db, server_id, not current.is_enabled, user)


@router.post("/{server_id}/sync")
async def sync_tools(server_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """同步远端工具清单：新建的默认停用，已有的更新描述与参数声明，远端消失的停用（不删除）。

    远端不可达返回 502 并写明原因（同时记进 last_error，页面能显示上次失败原因）。
    """
    return await mcp_service.sync_tools(db, server_id, user)


@router.delete("/{server_id}")
def delete_server(server_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """删除服务器。同步出来的工具保留但全部停用（不物理删除，避免破坏智能体的 tool_ids 引用）。"""
    mcp_service.delete_server(db, server_id, user)
    return {"code": 0, "message": "ok"}
