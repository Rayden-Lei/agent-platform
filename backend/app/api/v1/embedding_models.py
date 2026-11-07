"""向量模型路由：知识库建库时可选的 embedding 模型配置（增删改查、启停、连通测试、下拉候选）。

与 /models（对话模型）分开：调用协议不同（embeddings vs chat/completions），字段也不同（维度、单请求条数）。
创建 / 更新 / 删除 / 启停仅限 admin；查询、候选与连通测试允许 admin / developer。

密钥与对话模型同一口径：加密落库，任何接口只回 has_key，明文不出服务端。
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
from app.services import embedding_model_service

router = APIRouter(prefix="/embedding-models", tags=["embedding-models"])


class EmbeddingModelIn(BaseModel):
    """创建 / 更新请求体（整体覆盖）。

    dim 会被服务端与切片表列宽比对（不一致 422）：pgvector 是定长列，维度对不上入库必失败，
    因此不让它悄悄存进去。api_key 更新时留空表示沿用已有密钥。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=32)
    api_base: str = Field(min_length=1, max_length=255)
    api_key: str = Field("", max_length=512)
    model_name: str = Field(min_length=1, max_length=128)
    dim: int = Field(1024, ge=1, le=4096)
    request_size: int = Field(20, ge=1, le=500)
    is_enabled: bool = True


class EmbeddingBatchIn(BatchIn[Literal["enable", "disable", "delete"]]):
    """action 只接受 enable / disable / delete，其余值 422。"""


@router.get("")
def list_models(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    q: str | None = Query(None, max_length=64, description="名称模糊匹配"),
    provider: str | None = Query(None, max_length=32),
    is_enabled: bool | None = Query(None, description="只看启用 / 只看停用"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "developer")),
):
    """向量模型列表（分页），附被多少知识库绑定。"""
    return embedding_model_service.list_models(db, params, q, provider, is_enabled, sort)


# 固定路径必须声明在 /{model_id} 之前
@router.get("/options")
def list_options(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """建库下拉的候选清单：只列启用的，带维度。没有候选时返回空数组（前端据此引导去配置）。"""
    return {"items": embedding_model_service.options(db)}


@router.post("")
def create_model(data: EmbeddingModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """新建向量模型。维度必须与切片表列宽一致。仅 admin。"""
    return embedding_model_service.create_model(db, data, user)


@router.post("/batch")
def batch_models(data: EmbeddingBatchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """批量启用 / 停用 / 删除：逐条独立执行并返回成功与失败清单（被知识库绑定的进失败清单）。"""
    return run_batch(db, data.unique_ids(), lambda model_id: _batch_action(db, model_id, data.action, user))


def _batch_action(db: Session, model_id: int, action: str, user: User):
    if action == "delete":
        embedding_model_service.delete_model(db, model_id, user)
        return {"id": model_id}
    svc = embedding_model_service
    m = svc.get_model(db, model_id)  # 不存在则 404 进失败清单
    if m["is_enabled"] == (action == "enable"):
        return {"id": model_id}  # 已经是目标状态，幂等返回
    return svc.toggle_model(db, model_id, user)


@router.get("/{model_id}")
def get_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """按 ID 查询（含绑定它的知识库清单）。"""
    return embedding_model_service.get_model(db, model_id)


@router.put("/{model_id}")
def update_model(model_id: int, data: EmbeddingModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """覆盖式更新；api_key 留空沿用已有密钥。仅 admin。"""
    return embedding_model_service.update_model(db, model_id, data, user)


@router.post("/{model_id}/toggle")
def toggle_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """启用 / 停用。被知识库绑定时不能停用。仅 admin。"""
    return embedding_model_service.toggle_model(db, model_id, user)


@router.post("/{model_id}/test")
def test_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """连通测试：真的发一次 embeddings 请求并核对返回维度。失败返回 ok=false 带原因，不抛 5xx。"""
    return embedding_model_service.test_model(db, model_id)


@router.delete("/{model_id}")
def delete_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """删除。被知识库绑定时 409。仅 admin。"""
    embedding_model_service.delete_model(db, model_id, user)
    return {"ok": True}
