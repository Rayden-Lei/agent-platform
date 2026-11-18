"""工作流（Workflow）路由：工作流的增删改查、复制、批量删除、试运行、正式运行、人工审核续跑与运行记录，
以及发布 / 版本历史 / 回滚上线（FR-075）。

发布语义（docs/15 FR-075，与智能体 FR-039 同一套）：本模块读写的 graph 是**草稿**；
运行、工作流对话、定时任务、API Key 只读 published_version 指向的不可变快照。
除运行 / 续跑 / 参数声明显式允许 API Key 外，本模块接口仅允许 admin / developer 角色访问。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import current_api_key, require_roles
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
    """工作流正式运行请求体：inputs 为按开始节点声明填的变量字典（docs/15 WF-04，D-32 一次切换）。

    声明与校验在 workflow.io_contract：未声明的键 400、必填缺值 400、类型不符按声明宽松转换后仍不符 400。

    response_mode（docs/15 WF-05，FR-078）：
    - blocking（默认）：等执行结果，最多等 WORKFLOW_BLOCKING_TIMEOUT_S 秒，超时返回 202 + run_id 让调用方轮询。
      默认值必须保持 blocking —— 存量调用方（前端运行弹窗、既有测试）都按同步返回解析结果。
    - async：建完运行记录立刻返回 202 + run_id，后台继续跑。
    """

    inputs: dict = {}
    response_mode: Literal["blocking", "async"] = "blocking"


class TestRunIn(BaseModel):
    """工作流试运行请求体：graph 直接内联在请求中，不落库。"""

    graph: dict
    inputs: dict = {}


class ResumeIn(BaseModel):
    """工作流续跑请求体：decision 为人工审核节点的决策结果。"""

    decision: dict = {}


class WorkflowBatchIn(BatchIn[Literal["delete"]]):
    """action 只接受 "delete"，其余值 422。"""


class PublishIn(BaseModel):
    note: str | None = Field(None, max_length=200)  # 发布说明，进版本历史与审计


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
    附节点数、创建人、最近 7 天运行数、最近运行时间、定时任务数、线上版本与"有未发布改动"。

    status 语义（FR-075）：draft 从未发布、published 有线上版本。注意"有未发布改动"是独立的
    has_unpublished_changes —— 已发布的工作流改草稿后 status 仍是 published（线上还能跑）。"""
    return workflow_service.list_workflows(db, params, q, status, sort)


@router.post("")
def create_workflow(data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建工作流。graph 校验（并行 / 汇聚结构）不合法 400。"""
    return workflow_service.create_workflow(db, data, user)


# 固定路径必须声明在 /{workflow_id} 之前，否则 "test-run" / "batch" 会被当成 workflow_id 解析失败
@router.post("/test-run")
async def test_run_workflow(data: TestRunIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """试运行：用请求内联的 graph 直接执行，不落库；graph 或入参不合法 400。"""
    return await workflow_service.test_run_workflow(data.graph, data.inputs, role=user.role)


@router.post("/batch")
def batch_workflows(data: WorkflowBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量删除：逐条独立执行，被智能体引用的 409 进失败清单。"""
    return run_batch(db, data.unique_ids(), lambda workflow_id: workflow_service.apply_batch_action(db, workflow_id, data.action, user))


@router.get("/{workflow_id}")
def get_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """工作流详情（含 graph、节点统计、引用它的智能体、绑定的定时任务）。"""
    return workflow_service.get_workflow_detail(db, workflow_id)


@router.get("/{workflow_id}/parameters")
def get_workflow_parameters(workflow_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """开始 / 结束节点的输入输出声明（docs/15 WF-04）：运行弹窗、定时任务表单、API 访问页签按它生成表单项。

    开放 API Key 调用，外部系统可以据此知道该传哪些参数，不必读平台文档。
    Key 调用必须校验作用域：这个接口本来就开放给 Key，不校验就等于任意 Key 能枚举全部工作流的契约
    （2026-11-14 审计的横向越权）。
    """
    return workflow_service.workflow_parameters(db, workflow_id, api_key=current_api_key(request))


@router.put("/{workflow_id}")
def update_workflow(workflow_id: int, data: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 更新工作流**草稿**（草稿修订号 +1，线上不变）。graph 不合法 400。

    保存 ≠ 发布：要让改动对外生效（运行、对话、定时任务、API Key）必须再调 publish。
    """
    return workflow_service.update_workflow(db, workflow_id, data, user)


@router.post("/{workflow_id}/publish")
def publish_workflow(workflow_id: int, data: PublishIn | None = Body(None), db: Session = Depends(get_db),
                     user: User = Depends(require_roles("admin", "developer"))):
    """发布草稿成为线上版本（可带发布说明）；发布前跑完整图校验，不通过 400 且不生成版本。

    草稿与线上一致时 publish_result=unchanged，不生成新版本（幂等，双击不会连出两个版本）。
    """
    return workflow_service.publish_workflow(db, workflow_id, user, note=data.note if data else None)


@router.get("/{workflow_id}/versions")
def list_versions(workflow_id: int, params: PageParams = Depends(page_params), db: Session = Depends(get_db),
                  user: User = Depends(require_roles("admin", "developer"))):
    """发布版本历史（分页，按版本号倒序，含快照、发布人、说明、是否线上、节点数）。"""
    return workflow_service.list_versions(db, workflow_id, params)


@router.post("/{workflow_id}/rollback/{version_id}")
def rollback_workflow(workflow_id: int, version_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_roles("admin", "developer"))):
    """回滚上线：用该版本快照生成一个新版本并置为线上，**草稿不动**（与智能体 rollback 同一语义）。

    线上出事时一键止血，又不丢掉正在改的草稿；与线上一致时 publish_result=unchanged。
    """
    return workflow_service.rollback_workflow(db, workflow_id, version_id, user)


@router.post("/{workflow_id}/versions/{version_id}/restore")
def restore_version(workflow_id: int, version_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_roles("admin", "developer"))):
    """恢复到草稿：草稿 = 该版本快照，线上不变。用于"在旧版本基础上继续改"。"""
    return workflow_service.restore_version(db, workflow_id, version_id, user)


@router.post("/{workflow_id}/duplicate")
def duplicate_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """复制一份工作流（草稿态、名称加"副本"）。"""
    return workflow_service.duplicate_workflow(db, workflow_id, user)


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 删除工作流；被智能体引用时 409。"""
    workflow_service.delete_workflow(db, workflow_id, user)
    return {"code": 0, "message": "ok"}


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: int, data: RunIn, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """运行指定工作流。允许 API Key 调用，供外部系统触发执行（工作流须在 Key 的作用域内）；运行记录记下触发来源（ui / api_key）。

    response_mode（docs/15 WF-05）：blocking 等结果（默认，超时 202 + run_id）；async 立即 202 + run_id。
    并发已满 429，且在**建运行记录之前**拒绝 —— 不留一条永远没人执行的 running 记录。
    """
    result = await workflow_service.run_workflow(db, workflow_id, data.inputs, user, api_key=current_api_key(request),
                                                 response_mode=data.response_mode)
    if isinstance(result, workflow_service.AcceptedRun):
        response.status_code = 202
        return result.payload
    return result


@router.post("/{workflow_id}/runs/{run_id}/resume")
async def resume_workflow(workflow_id: int, run_id: int, data: ResumeIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """人工审核通过 / 驳回后续跑。允许 API Key 调用：工作流须在作用域内，且只能续跑本 Key 发起的运行。"""
    return await workflow_service.resume_workflow(db, workflow_id, run_id, data.decision, api_key=current_api_key(request))


@router.get("/{workflow_id}/runs/{run_id}")
def get_workflow_run(workflow_id: int, run_id: int, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """查一条工作流的运行（docs/15 WF-05，FR-078）：状态、输出、节点执行结果，供异步运行的调用方轮询。

    允许 API Key 调用，但**只能查本 Key 发起的运行**（与续跑同一套行级校验）：不属于该工作流或不属于本 Key
    一律 404「运行记录不存在」，不暴露存在性。JWT 请求的口径不变。
    """
    return workflow_service.get_workflow_run(db, workflow_id, run_id, api_key=current_api_key(request))


@router.post("/{workflow_id}/runs/{run_id}/cancel")
def cancel_workflow_run(workflow_id: int, run_id: int, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require_roles("admin", "developer", allow_api_key=True))):
    """取消一条运行中的工作流（docs/15 WF-05）：状态变 cancelled，引擎在下一个节点开始前停下。

    只限本 Key 发起的运行（同查询接口的行级校验）。重复取消已取消的返回 200 且状态不变；
    已 success / failed / awaiting_review 的返回 409；不存在或不属于本 Key 的 404。
    """
    return workflow_service.cancel_workflow_run(db, workflow_id, run_id, api_key=current_api_key(request))


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
