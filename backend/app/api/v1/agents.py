"""智能体（Agent）管理路由。

提供智能体的增删改查、发布与下线、批量操作、版本管理（恢复到草稿 / 回滚上线）接口。
发布语义（docs/15 3.2，FR-039）：本模块读写的配置是草稿；对话、API Key、工作流智能体节点只读线上版本。
除显式注明外，本模块接口仅允许 admin / developer 角色访问；
路由签名中的 user 参数用于触发 require_roles 鉴权依赖，函数体可能不会直接使用它。
"""

from typing import Literal

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import get_current_user, require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import AgentBriefOut, AgentDetailOut, AgentIn, AgentOut, AgentPublishOut, AgentUpdateIn, Page, PublishIn
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentBatchIn(BatchIn):
    action: Literal["publish", "offline", "delete"]


@router.get("", response_model=Page[AgentOut])
def list_agents(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    status: Literal["draft", "published", "offline"] | None = Query(None),
    model_id: int | None = Query(None),
    kb_id: int | None = Query(None, description="绑定了该知识库的智能体"),
    tool_id: int | None = Query(None, description="绑定了该工具的智能体"),
    prompt_template_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """智能体列表。支持名称模糊、状态、模型、知识库、工具、模板筛选；sort 可选 id / name / status / version / updated_at；
    附模型名、模板名、创建人、线上版本与"有未发布修改"、最近 7 天运行数（不计调试）与最近运行时间。"""
    return agent_service.list_agents(db, params, q, status, model_id, kb_id, tool_id, prompt_template_id, sort)


@router.post("", response_model=AgentOut)
def create_agent(data: AgentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建智能体（草稿）。引用校验与模板渲染在 service 层完成。"""
    return agent_service.create_agent(db, data, user)


# 固定路径必须声明在 /{agent_id} 之前
@router.post("/batch")
def batch_agents(data: AgentBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量发布 / 下线 / 删除：逐条独立执行并返回成功与失败清单。"""
    return run_batch(db, data.unique_ids(), lambda agent_id: agent_service.apply_batch_action(db, agent_id, data.action, user))


@router.get("/available", response_model=Page[AgentBriefOut])
def list_available_agents(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """可对话的智能体（本模块唯一不限角色的接口）：任何登录身份都可调，含 caller 与 API Key。
    只返回已发布的，且只带 id / 名称 / 描述 / 发布时间，名称与描述取线上快照。对话页下拉用它，外部系统也用它发现可调的智能体。"""
    return agent_service.list_available_agents(db, params, q)


@router.get("/available/{agent_id}", response_model=AgentBriefOut)
def get_available_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """单个可对话智能体的对外资料（任何登录身份含 API Key）：不存在 404、未发布或已下线 403。
    深链进对话页、可对话智能体超过一页时用它定位当前智能体（docs/15 AG-05）。"""
    return agent_service.get_available_agent(db, agent_id)


@router.get("/{agent_id}", response_model=AgentDetailOut)
def get_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """智能体详情（草稿）：基础字段 + 线上版本信息 + 关联的模型 / 工具 / 知识库 / 工作流 / 模板对象与悬空引用清单。"""
    return agent_service.get_agent_detail(db, agent_id)


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, data: AgentUpdateIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """整体覆盖草稿，发布后才对外生效。expected_updated_at 过期 409。"""
    return agent_service.update_agent(db, agent_id, data, user)


@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 删除智能体。删除成功后返回统一成功响应。"""
    agent_service.delete_agent(db, agent_id)
    return {"code": 0, "message": "ok"}


@router.post("/{agent_id}/publish", response_model=AgentPublishOut)
def publish_agent(agent_id: int, data: PublishIn | None = Body(None), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """发布草稿成为线上版本（可带发布说明）；与线上一致时 publish_result=unchanged，不生成版本。"""
    return agent_service.publish_agent(db, agent_id, user, note=data.note if data else None)


@router.post("/{agent_id}/offline")
def offline_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """下线：对外入口 403「智能体已下线」，重新发布即恢复。返回 {id, status}。"""
    return agent_service.offline_agent(db, agent_id, user)


@router.get("/{agent_id}/versions")
def list_versions(agent_id: int, params: PageParams = Depends(page_params), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """发布版本列表（分页，含快照、发布人、说明、是否线上）。"""
    return agent_service.list_versions(db, agent_id, params)


@router.post("/{agent_id}/versions/{version_id}/restore", response_model=AgentOut)
def restore_version(agent_id: int, version_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """恢复到草稿：草稿 = 该版本快照，线上不变。"""
    return agent_service.restore_version(db, agent_id, version_id, user)


@router.post("/{agent_id}/rollback/{version_id}", response_model=AgentPublishOut)
def rollback_agent(agent_id: int, version_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """回滚上线：用该版本快照生成新版本并置为线上，草稿不动；与线上一致时 unchanged。"""
    return agent_service.rollback_agent(db, agent_id, version_id, user)
