from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.core.security import hash_password
from app.db.models import Agent, KnowledgeBase, ModelConfig, User, Workflow
from app.schemas import UserCreate, UserUpdate


def list_users(db: Session, params: PageParams, q: str = None) -> dict:
    """分页列出用户，q 对用户名模糊匹配。"""
    query = db.query(User)
    if q:
        query = query.filter(User.username.ilike(f"%{q}%"))
    return paginate(query.order_by(User.id), params)


def create_user(db: Session, data: UserCreate) -> User:
    """新建用户：用户名唯一性先查库（DB 唯一约束兜底），密码只存哈希。"""
    if db.query(User).filter(User.username == data.username).first():
        raise BizError(409, "用户名已存在")
    u = User(username=data.username, password_hash=hash_password(data.password), role=data.role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def get_user(db: Session, user_id: int) -> User:
    """按 ID 取用户，不存在抛 BizError(404)。"""
    u = db.get(User, user_id)
    if u is None:
        raise BizError(404, "用户不存在")
    return u


def update_user(db: Session, user_id: int, data: UserUpdate) -> User:
    """更新用户：只处理显式传入的字段（role / is_active），其余保持不动。"""
    u = get_user(db, user_id)
    if data.role is not None:
        u.role = data.role
    if data.is_active is not None:
        u.is_active = data.is_active
    db.commit()
    db.refresh(u)
    return u


def delete_user(db: Session, user_id: int) -> None:
    """删除用户：先检查其名下配置类资源，有引用则拒绝删除（RESTRICT 保护）。"""
    u = get_user(db, user_id)
    # 配置类引用（created_by）使用 RESTRICT，删除前给出友好提示
    refs = []
    if db.query(ModelConfig).filter(ModelConfig.created_by == user_id).first():
        refs.append("模型")
    if db.query(Agent).filter(Agent.created_by == user_id).first():
        refs.append("智能体")
    if db.query(KnowledgeBase).filter(KnowledgeBase.created_by == user_id).first():
        refs.append("知识库")
    if db.query(Workflow).filter(Workflow.created_by == user_id).first():
        refs.append("工作流")
    if refs:
        raise BizError(409, "该用户仍关联配置资源（" + "、".join(refs) + "），无法删除")
    db.delete(u)
    db.commit()
