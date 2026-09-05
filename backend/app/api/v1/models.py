"""模型（LLM）配置路由：模型的增删改查、启停、批量操作与连通性测试。

创建 / 更新 / 删除 / 启停仅限 admin 角色，查询与测试允许 admin / developer。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.batch import BatchIn, run_batch
from app.core.deps import require_roles
from app.core.pagination import PageParams, SortParams, page_params, sort_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import ModelIn, ModelOut, Page
from app.services import model_service

router = APIRouter(prefix="/models", tags=["models"])


class ModelBatchIn(BatchIn):
    action: Literal["enable", "disable", "delete"]


@router.get("", response_model=Page[ModelOut])
def list_models(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    provider: str | None = Query(None, max_length=32),
    is_enabled: bool | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """模型列表（分页），支持名称模糊、提供商、启用状态过滤；sort 可选 id / name / provider / updated_at。"""
    return model_service.list_models(db, params, q, provider, is_enabled, sort)


@router.post("", response_model=ModelOut)
def create_model(data: ModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """新建模型配置。仅 admin。"""
    return model_service.create_model(db, data, user)


# 固定路径必须声明在 /{model_id} 之前
@router.post("/batch")
def batch_models(data: ModelBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """批量启用 / 停用 / 删除：逐条独立执行并返回成功与失败清单（被引用的模型删除 409 进失败清单）。仅 admin。"""
    return run_batch(db, data.unique_ids(), lambda model_id: model_service.apply_batch_action(db, model_id, data.action, user))


@router.get("/{model_id}")
def get_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询模型配置（含引用它的智能体清单）。"""
    return model_service.get_model_detail(db, model_id)


@router.put("/{model_id}", response_model=ModelOut)
def update_model(model_id: int, data: ModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """按 ID 更新模型配置。仅 admin。"""
    return model_service.update_model(db, model_id, data)


@router.post("/{model_id}/toggle")
def toggle_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """启用 / 停用模型（开关切换）。仅 admin；停用后引用它的智能体对话返回 400。"""
    current = model_service.get_model(db, model_id)
    return model_service.set_model_enabled(db, model_id, not current.is_enabled, user)


@router.delete("/{model_id}")
def delete_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """按 ID 删除模型配置。仅 admin。"""
    model_service.delete_model(db, model_id, user)
    return {"code": 0, "message": "ok"}


@router.post("/{model_id}/test")
async def test_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """测试模型连通性：调用一次模型接口并返回测试结果。"""
    data = await model_service.test_model(db, model_id)
    return {"code": 0, "message": "ok", "data": data}
