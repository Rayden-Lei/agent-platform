"""智能体（Agent）管理路由。

提供智能体的增删改查、发布、批量操作、版本管理与回滚接口。
除显式注明外，本模块接口仅允许 admin / developer 角色访问；
路由签名中的 user 参数用于触发 require_roles 鉴权依赖，函数体可能不会直接使用它。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import AgentDetailOut, AgentIn, AgentOut, Page
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentBatchIn(BatchIn):
    action: Literal["publish", "delete"]


@router.get("", response_model=Page[AgentOut])
def list_agents(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    status: Literal["draft", "published"] | None = Query(None),
    model_id: int | None = Query(None),
    kb_id: int | None = Query(None, description="绑定了该知识库的智能体"),
    tool_id: int | None = Query(None, description="绑定了该工具的智能体"),
    prompt_template_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """智能体列表。支持名称模糊、状态、模型、知识库、工具、模板筛选；sort 可选 id / name / status / version / updated_at；
    附模型名、模板名、创建人、最近 7 天运行数与最近运行时间。"""
    return agent_service.list_agents(db, params, q, status, model_id, kb_id, tool_id, prompt_template_id, sort)


@router.post("", response_model=AgentOut)
def create_agent(data: AgentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建智能体。请求体 AgentIn 的校验与落库在 service 层完成。"""
    return agent_service.create_agent(db, data, user)


# 固定路径必须声明在 /{agent_id} 之前
@router.post("/batch")
def batch_agents(data: AgentBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """批量发布 / 删除：逐条独立执行并返回成功与失败清单。"""
    return run_batch(db, data.unique_ids(), lambda agent_id: agent_service.apply_batch_action(db, agent_id, data.action, user))


@router.get("/{agent_id}", response_model=AgentDetailOut)
def get_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """智能体详情：基础字段 + 关联的模型 / 工具 / 知识库 / 工作流 / 模板对象与悬空引用清单。"""
    return agent_service.get_agent_detail(db, agent_id)


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, data: AgentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 更新智能体。"""
    return agent_service.update_agent(db, agent_id, data)


@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 删除智能体。删除成功后返回统一成功响应。"""
    agent_service.delete_agent(db, agent_id)
    return {"code": 0, "message": "ok"}


@router.post("/{agent_id}/publish", response_model=AgentOut)
def publish_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """发布智能体：为当前版本生成一条发布记录，供运行使用。"""
    return agent_service.publish_agent(db, agent_id, user)


@router.get("/{agent_id}/versions")
def list_versions(agent_id: int, params: PageParams = Depends(page_params), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """查询智能体的历史版本列表（分页，含快照）。"""
    return agent_service.list_versions(db, agent_id, params)


@router.post("/{agent_id}/rollback/{version_id}")
def rollback_agent(agent_id: int, version_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """将智能体回滚到指定历史版本。"""
    return agent_service.rollback_agent(db, agent_id, version_id)
