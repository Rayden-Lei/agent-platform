"""工作流（Workflow）路由：工作流的增删改查、复制、批量删除、试运行、正式运行、人工审核续跑与运行记录。

除运行 / 续跑显式允许 API Key 外，本模块接口仅允许 admin / developer 角色访问。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import is_api_key_request, require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params, time_range
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


class WorkflowBatchIn(BatchIn):
    action: Literal["delete"]


@router.get("")
def list_workflows(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    status: Literal["draft", "published"] | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """工作流列表（分页），支持名称模糊、状态过滤；sort 可选 id / name / status / version / updated_at；
    附节点数、创建人、最近 7 天运行数、最近运行时间、定时任务数。"""
    return workflow_service.list_workflows(db, params, q, status, sort)


@router.post("")
def create_workflow(data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建工作流。graph 校验（并行 / 汇聚结构）不合法 400。"""
    return workflow_service.create_workflow(db, data, user)


# 固定路径必须声明在 /{workflow_id} 之前，否则 "test-run" / "batch" 会被当成 workflow_id 解析失败
@router.post("/test-run")
async def test_run_workflow(data: TestRunIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """试运行：用请求内联的 graph 直接执行，不落库；graph 不合法 400。"""
    return await workflow_service.test_run_workflow(data.graph, data.input, role=user.role)


@router.post("/batch")
def batch_workflows(data: WorkflowBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量删除：逐条独立执行，被智能体引用的 409 进失败清单。"""
    return run_batch(db, data.unique_ids(), lambda workflow_id: workflow_service.apply_batch_action(db, workflow_id, data.action))


@router.get("/{workflow_id}")
def get_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """工作流详情（含 graph、节点统计、引用它的智能体、绑定的定时任务）。"""
    return workflow_service.get_workflow_detail(db, workflow_id)


@router.put("/{workflow_id}")
def update_workflow(workflow_id: int, data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 更新工作流（版本号 +1）。graph 不合法 400。"""
    return workflow_service.update_workflow(db, workflow_id, data)


@router.post("/{workflow_id}/duplicate")
def duplicate_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """复制一份工作流（草稿态、名称加"副本"）。"""
    return workflow_service.duplicate_workflow(db, workflow_id, user)


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 删除工作流；被智能体引用时 409。"""
    workflow_service.delete_workflow(db, workflow_id)
    return {"code": 0, "message": "ok"}


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: int, data: RunIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """运行指定工作流。允许 API Key 调用，供外部系统触发执行；运行记录记下触发来源（ui / api_key）。"""
    source = "api_key" if is_api_key_request(request) else "ui"
    return await workflow_service.run_workflow(db, workflow_id, data.input, user, source=source)


@router.post("/{workflow_id}/runs/{run_id}/resume")
async def resume_workflow(workflow_id: int, run_id: int, data: ResumeIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """人工审核通过 / 驳回后续跑。允许 API Key 调用。"""
    return await workflow_service.resume_workflow(db, workflow_id, run_id, data.decision)


@router.get("/{workflow_id}/runs")
def list_runs(
    workflow_id: int,
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    status: Literal["running", "success", "failed", "cancelled", "awaiting_review"] | None = Query(None),
    started_from: datetime | None = Query(None),
    started_to: datetime | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """某工作流的运行记录（分页），字段与全局运行记录一致；可按状态、发起时间区间过滤与排序。"""
    started_from, started_to = time_range(started_from, started_to)
    return workflow_service.list_workflow_runs(db, workflow_id, params, status, started_from, started_to, sort)
