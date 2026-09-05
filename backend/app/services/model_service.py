import logging

from langchain_core.messages import HumanMessage
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.security import encrypt_secret
from app.db.models import Agent, ModelConfig, User
from app.model_gateway.gateway import build_llm, guarded_ainvoke
from app.schemas import ModelIn

logger = logging.getLogger(__name__)

SORTABLE = {"id": ModelConfig.id, "name": ModelConfig.name, "provider": ModelConfig.provider, "updated_at": ModelConfig.updated_at}


def _to_dict(m: ModelConfig, agents_count: int = 0, creator: str | None = None) -> dict:
    """模型配置 → 对外字典（永不带密钥），附引用智能体数与创建人。"""
    return {
        "id": m.id, "name": m.name, "provider": m.provider, "api_base": m.api_base, "model_name": m.model_name,
        "default_params": m.default_params or {}, "is_enabled": m.is_enabled,
        "price_input": m.price_input, "price_output": m.price_output,
        "agents_count": agents_count, "created_by": m.created_by, "created_by_username": creator,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _related(db: Session, models: list) -> tuple[dict, dict]:
    ids = {m.id for m in models}
    counts = dict(db.query(Agent.model_id, func.count(Agent.id)).filter(Agent.model_id.in_(ids)).group_by(Agent.model_id).all()) if ids else {}
    creator_ids = {m.created_by for m in models if m.created_by}
    creators = dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
    return counts, creators


def list_models(db: Session, params: PageParams, q: str = None, provider: str = None, is_enabled: bool = None, sort: SortParams = None) -> dict:
    """分页列出模型配置：q 名称模糊，可按提供商、启用状态过滤，白名单排序；引用智能体数与创建人各一次查询装配。"""
    query = db.query(ModelConfig)
    if q:
        query = query.filter(ModelConfig.name.ilike(f"%{q}%"))
    if provider:
        query = query.filter(ModelConfig.provider == provider)
    if is_enabled is not None:
        query = query.filter(ModelConfig.is_enabled.is_(is_enabled))
    page = paginate(apply_sort(query, sort, SORTABLE, [ModelConfig.id.asc()]), params)
    counts, creators = _related(db, page["items"])
    page["items"] = [_to_dict(m, int(counts.get(m.id, 0)), creators.get(m.created_by)) for m in page["items"]]
    return page


def create_model(db: Session, data: ModelIn, user: User) -> dict:
    """新建模型配置：API Key 加密后落库（库中不存明文），并写审计。"""
    if not data.api_key:
        raise BizError(400, "新建模型必须填写 API Key")
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
    return _to_dict(m, 0, user.username)


def get_model(db: Session, model_id: int) -> ModelConfig:
    """按 ID 取模型配置，不存在抛 BizError(404)。"""
    m = db.get(ModelConfig, model_id)
    if m is None:
        raise BizError(404, "模型不存在")
    return m


def get_model_detail(db: Session, model_id: int) -> dict:
    """模型详情：附引用它的智能体清单。"""
    m = get_model(db, model_id)
    agents = [{"id": a.id, "name": a.name, "status": a.status} for a in db.query(Agent).filter(Agent.model_id == model_id).order_by(Agent.id).all()]
    _, creators = _related(db, [m])
    return {**_to_dict(m, len(agents), creators.get(m.created_by)), "agents": agents}


def update_model(db: Session, model_id: int, data: ModelIn) -> dict:
    """覆盖式更新模型配置；api_key 为空表示沿用已有密钥，仅当提交了新的非空 Key 时才重新加密覆盖。"""
    m = get_model(db, model_id)
    m.name = data.name
    m.provider = data.provider
    m.api_base = data.api_base
    if data.api_key:
        m.api_key_enc = encrypt_secret(data.api_key)
    m.model_name = data.model_name
    m.default_params = data.default_params
    m.price_input = data.price_input
    m.price_output = data.price_output
    db.commit()
    db.refresh(m)
    counts, creators = _related(db, [m])
    return _to_dict(m, int(counts.get(m.id, 0)), creators.get(m.created_by))


def set_model_enabled(db: Session, model_id: int, enabled: bool, user: User) -> dict:
    """启用 / 停用模型（幂等）。停用后引用它的智能体对话直接 400"模型不可用"，写审计便于追溯是谁停的。"""
    m = get_model(db, model_id)
    if m.is_enabled != enabled:
        m.is_enabled = enabled
        db.commit()
        record_audit(db, user, "enable" if enabled else "disable", "model", m.id, detail={"name": m.name})
    return {"id": m.id, "is_enabled": m.is_enabled}


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


def apply_batch_action(db: Session, model_id: int, action: str, user: User) -> None:
    """批量操作的单条执行（enable / disable / delete）。"""
    if action == "delete":
        delete_model(db, model_id, user)
    else:
        set_model_enabled(db, model_id, action == "enable", user)


async def test_model(db: Session, model_id: int) -> dict:
    """连通性测试：发一条 ping 看模型是否可用。失败不抛异常，返回 ok=False 供前端展示。

    以探测模式绕过熔断的打开期判定：成功即关闭该模型的熔断，是人工恢复的手段。
    """
    m = get_model(db, model_id)
    try:
        llm = build_llm(m)
        resp = await guarded_ainvoke(m, llm, [HumanMessage(content="ping")], probe=True)
        return {"ok": True, "reply": (resp.content or "")[:100]}
    except Exception as e:
        # 连通性测试的失败本身就是结果，返回给前端展示；同时留日志便于排查是网络还是鉴权
        logger.warning("模型连通性测试失败 model_id=%s name=%s error=%s", model_id, m.name, e)
        return {"ok": False, "error": str(e)[:300]}
