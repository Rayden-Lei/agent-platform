"""智能体（Agent）管理路由。

提供智能体的增删改查、发布、版本管理与回滚接口。
除显式注明外，本模块接口仅允许 admin / developer 角色访问；
路由签名中的 user 参数用于触发 require_roles 鉴权依赖，函数体可能不会直接使用它。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import AgentIn, AgentOut, Page
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=Page[AgentOut])
def list_agents(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    status: Literal["draft", "published"] | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """智能体列表。支持按名称模糊匹配、按状态筛选，分页参数由 page_params 注入。"""
    return agent_service.list_agents(db, params, q, status)


@router.post("", response_model=AgentOut)
def create_agent(data: AgentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """新建智能体。请求体 AgentIn 的校验与落库在 service 层完成。"""
    return agent_service.create_agent(db, data, user)


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询单个智能体详情。"""
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
    """查询智能体的历史版本列表（分页）。"""
    return agent_service.list_versions(db, agent_id, params)


@router.post("/{agent_id}/rollback/{version_id}")
def rollback_agent(agent_id: int, version_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """将智能体回滚到指定历史版本。"""
    return agent_service.rollback_agent(db, agent_id, version_id)
