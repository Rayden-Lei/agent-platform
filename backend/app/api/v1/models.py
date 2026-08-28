from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from langchain_core.messages import HumanMessage

from app.core.audit import record_audit
from app.core.deps import require_roles
from app.core.security import encrypt_secret
from app.db.models import ModelConfig, User
from app.db.session import get_db
from app.model_gateway.gateway import build_llm
from app.schemas import ModelIn, ModelOut

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelOut])
def list_models(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return db.query(ModelConfig).order_by(ModelConfig.id).all()


@router.post("", response_model=ModelOut)
def create_model(data: ModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
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
    return ModelOut.model_validate(m)


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    m = db.get(ModelConfig, model_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    return ModelOut.model_validate(m)


@router.put("/{model_id}", response_model=ModelOut)
def update_model(model_id: int, data: ModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    m = db.get(ModelConfig, model_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
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
    return ModelOut.model_validate(m)


@router.delete("/{model_id}")
def delete_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    m = db.get(ModelConfig, model_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    record_audit(db, user, "delete", "model", model_id, detail={"name": m.name})
    db.delete(m)
    db.commit()
    return {"code": 0, "message": "ok"}


@router.post("/{model_id}/test")
async def test_model(model_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    m = db.get(ModelConfig, model_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    try:
        llm = build_llm(m)
        resp = await llm.ainvoke([HumanMessage(content="ping")])
        return {"code": 0, "message": "ok", "data": {"ok": True, "reply": (resp.content or "")[:100]}}
    except Exception as e:
        return {"code": 0, "message": "ok", "data": {"ok": False, "error": str(e)[:300]}}
