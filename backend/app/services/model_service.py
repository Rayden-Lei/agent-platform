import logging

from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.core.security import encrypt_secret
from app.db.models import Agent, ModelConfig, User
from app.model_gateway.gateway import build_llm
from app.schemas import ModelIn

logger = logging.getLogger(__name__)


def list_models(db: Session, params: PageParams, q: str = None) -> dict:
    """分页列出模型配置，q 对名称模糊匹配。"""
    query = db.query(ModelConfig)
    if q:
        query = query.filter(ModelConfig.name.ilike(f"%{q}%"))
    return paginate(query.order_by(ModelConfig.id), params)


def create_model(db: Session, data: ModelIn, user: User) -> ModelConfig:
    """新建模型配置：API Key 加密后落库（库中不存明文），并写审计。"""
    m = ModelConfig(
        name=data.name,
        provider=data.provider,
        api_base=data.api_base,
        api_key_enc=encrypt_secret(data.api_key),
        model_name=data.model_name,
        default_params=data.default_params,
        price_input=data.price_input,
        price_output=data.price_output,
        created_by=user.id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    record_audit(db, user, "create", "model", m.id, detail={"name": m.name})
    return m


def get_model(db: Session, model_id: int) -> ModelConfig:
    """按 ID 取模型配置，不存在抛 BizError(404)。"""
    m = db.get(ModelConfig, model_id)
    if m is None:
        raise BizError(404, "模型不存在")
    return m


def update_model(db: Session, model_id: int, data: ModelIn) -> ModelConfig:
    """覆盖式更新模型配置；注意每次更新都会用新提交的 API Key 重新加密覆盖。"""
    m = get_model(db, model_id)
    m.name = data.name
    m.provider = data.provider
    m.api_base = data.api_base
    m.api_key_enc = encrypt_secret(data.api_key)
    m.model_name = data.model_name
    m.default_params = data.default_params
    m.price_input = data.price_input
    m.price_output = data.price_output
    db.commit()
    db.refresh(m)
    return m


def delete_model(db: Session, model_id: int, user: User) -> None:
    """删除模型：先检查智能体引用，有引用则拒绝删除（避免悬空 model_id），删除前写审计。"""
    m = get_model(db, model_id)
    # agents.model_id 是外键，直接删会被数据库拒绝，这里提前给出可读的错误
    ref_count = db.query(Agent).filter(Agent.model_id == model_id).count()
    if ref_count:
        raise BizError(409, f"该模型已被 {ref_count} 个智能体引用，无法删除")
    record_audit(db, user, "delete", "model", model_id, detail={"name": m.name})
    db.delete(m)
    db.commit()


async def test_model(db: Session, model_id: int) -> dict:
    """连通性测试：发一条 ping 看模型是否可用。失败不抛异常，返回 ok=False 供前端展示。"""
    m = get_model(db, model_id)
    try:
        llm = build_llm(m)
        resp = await llm.ainvoke([HumanMessage(content="ping")])
        return {"ok": True, "reply": (resp.content or "")[:100]}
    except Exception as e:
        # 连通性测试的失败本身就是结果，返回给前端展示；同时留日志便于排查是网络还是鉴权
        logger.warning("模型连通性测试失败 model_id=%s name=%s error=%s", model_id, m.name, e)
        return {"ok": False, "error": str(e)[:300]}
