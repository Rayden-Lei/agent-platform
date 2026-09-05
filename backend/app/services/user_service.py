from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.security import hash_password
from app.db.models import Agent, KnowledgeBase, ModelConfig, User, Workflow
from app.schemas import UserCreate, UserUpdate

SORTABLE = {"id": User.id, "username": User.username, "created_at": User.created_at}


def list_users(db: Session, params: PageParams, q: str = None, role: str = None, is_active: bool = None, sort: SortParams = None) -> dict:
    """分页列出用户：q 用户名模糊，可按角色、启用状态过滤，白名单排序。"""
    query = db.query(User)
    if q:
        query = query.filter(User.username.ilike(f"%{q}%"))
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))
    return paginate(apply_sort(query, sort, SORTABLE, [User.id.asc()]), params)


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


def update_user(db: Session, user_id: int, data: UserUpdate, operator: User = None) -> User:
    """更新用户：只处理显式传入的字段（role / is_active），其余保持不动。管理员不能停用或降级自己，避免把自己锁在门外。"""
    u = get_user(db, user_id)
    if operator is not None and operator.id == user_id and (data.is_active is False or (data.role is not None and data.role != "admin")):
        raise BizError(400, "不能停用或降级当前登录的管理员账号")
    if data.role is not None:
        u.role = data.role
    if data.is_active is not None:
        u.is_active = data.is_active
    db.commit()
    db.refresh(u)
    return u


def reset_password(db: Session, user_id: int, new_password: str, operator: User) -> None:
    """管理员重置用户密码（只存哈希），写审计但不记录密码。"""
    u = get_user(db, user_id)
    u.password_hash = hash_password(new_password)
    db.commit()
    record_audit(db, operator, "reset_password", "user", u.id, detail={"username": u.username})


def delete_user(db: Session, user_id: int, operator: User = None) -> None:
    """删除用户：先检查其名下配置类资源，有引用则拒绝删除（RESTRICT 保护）；不能删除自己。"""
    u = get_user(db, user_id)
    if operator is not None and operator.id == user_id:
        raise BizError(400, "不能删除当前登录的账号")
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


def apply_batch_action(db: Session, user_id: int, action: str, operator: User) -> None:
    """批量操作的单条执行（enable / disable / delete），对自己的停用 / 删除按 400 进失败清单。"""
    if action == "delete":
        delete_user(db, user_id, operator)
    else:
        update_user(db, user_id, UserUpdate(is_active=(action == "enable")), operator)
