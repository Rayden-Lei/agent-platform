from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.security import hash_password
from app.db.models import User
from app.db.session import get_db
from app.schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
    u = User(username=data.username, password_hash=hash_password(data.password), role=data.role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return UserOut.model_validate(u)


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if data.role is not None:
        u.role = data.role
    if data.is_active is not None:
        u.is_active = data.is_active
    db.commit()
    db.refresh(u)
    return UserOut.model_validate(u)


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    db.delete(u)
    db.commit()
    return {"code": 0, "message": "ok"}
