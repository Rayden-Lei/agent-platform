"""工作流路由：工作流的增删改查、试运行、正式运行与人工审核续跑。

管理类接口仅允许 admin / developer 角色访问；运行 / 续跑接口显式允许 API Key 调用，
供外部系统触发执行（见 require_roles 的 allow_api_key 参数）。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.services import workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowIn(BaseModel):
    """创建 / 更新工作流的请求体：graph 为工作流图定义（节点与连线）。"""

    name: str
    description: str = ""
    graph: dict


class RunIn(BaseModel):
    """工作流正式运行请求体：input 为运行输入。"""

    input: str = ""


class TestRunIn(BaseModel):
    """工作流试运行请求体：graph 直接内联在请求中，不落库。"""

    graph: dict
    input: str = ""


class ResumeIn(BaseModel):
    """工作流续跑请求体：decision 为人工审核节点的决策结果。"""

    decision: dict = {}


@router.get("")
def list_workflows(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """工作流列表（分页），支持名称模糊匹配。"""
    return workflow_service.list_workflows(db, params, q)


@router.post("")
def create_workflow(data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建工作流。"""
    return workflow_service.create_workflow(db, data, user)


# 固定路径必须声明在 /{workflow_id} 之前，否则 "test-run" 会被当成 workflow_id 解析失败
@router.post("/test-run")
async def test_run_workflow(data: TestRunIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """试运行工作流：使用请求内联的 graph，不保存工作流本身。"""
    return await workflow_service.test_run_workflow(data.graph, data.input, role=user.role)


@router.get("/{workflow_id}")
def get_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询工作流详情（含 graph 定义）。"""
    return workflow_service.get_workflow_detail(db, workflow_id)


@router.put("/{workflow_id}")
def update_workflow(workflow_id: int, data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 更新工作流。"""
    return workflow_service.update_workflow(db, workflow_id, data)


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 删除工作流。"""
    workflow_service.delete_workflow(db, workflow_id)
    return {"code": 0, "message": "ok"}


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: int, data: RunIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """运行指定工作流。允许 API Key 调用，供外部系统触发执行。"""
    return await workflow_service.run_workflow(db, workflow_id, data.input, user)


@router.post("/{workflow_id}/runs/{run_id}/resume")
async def resume_workflow(workflow_id: int, run_id: int, data: ResumeIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """对处于 awaiting_review 的运行提交审核决策并继续执行。允许 API Key 调用。"""
    return await workflow_service.resume_workflow(db, workflow_id, run_id, data.decision)


@router.get("/{workflow_id}/runs")
def list_runs(
    workflow_id: int,
    params: PageParams = Depends(page_params),
    status: Literal["running", "success", "failed", "cancelled", "awaiting_review"] | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """指定工作流的运行记录列表（分页），可按状态过滤。"""
    return workflow_service.list_workflow_runs(db, workflow_id, params, status)
