from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.security import encrypt_secret
from app.db.models import Agent, ModelConfig, User
from app.model_gateway.gateway import build_llm
from app.schemas import ModelIn


def list_models(db: Session) -> list[ModelConfig]:
    return db.query(ModelConfig).order_by(ModelConfig.id).all()


def create_model(db: Session, data: ModelIn, user: User) -> ModelConfig:
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
    m = db.get(ModelConfig, model_id)
    if m is None:
        raise BizError(404, "模型不存在")
    return m


def update_model(db: Session, model_id: int, data: ModelIn) -> ModelConfig:
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
    m = get_model(db, model_id)
    ref_count = db.query(Agent).filter(Agent.model_id == model_id).count()
    if ref_count:
        raise BizError(409, f"该模型已被 {ref_count} 个智能体引用，无法删除")
    record_audit(db, user, "delete", "model", model_id, detail={"name": m.name})
    db.delete(m)
    db.commit()


async def test_model(db: Session, model_id: int) -> dict:
    m = get_model(db, model_id)
    try:
        llm = build_llm(m)
        resp = await llm.ainvoke([HumanMessage(content="ping")])
        return {"ok": True, "reply": (resp.content or "")[:100]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
