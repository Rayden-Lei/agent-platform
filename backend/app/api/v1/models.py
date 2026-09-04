"""模型（LLM）配置路由：模型的增删改查与连通性测试。

创建 / 更新 / 删除仅限 admin 角色，查询与测试允许 admin / developer。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.pagination import PageParams, page_params
from app.db.models import User
from app.db.session import get_db
from app.schemas import ModelIn, ModelOut, Page
from app.services import model_service

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=Page[ModelOut])
def list_models(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """模型列表（分页），支持名称模糊匹配。"""
    return model_service.list_models(db, params, q)


@router.post("", response_model=ModelOut)
def create_model(data: ModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """新建模型配置。仅 admin。"""
    return model_service.create_model(db, data, user)


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询模型配置。"""
    return model_service.get_model(db, model_id)


@router.put("/{model_id}", response_model=ModelOut)
def update_model(model_id: int, data: ModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """按 ID 更新模型配置。仅 admin。"""
    return model_service.update_model(db, model_id, data)


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
