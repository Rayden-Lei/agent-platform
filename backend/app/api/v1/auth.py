import redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import record_audit
from app.core.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.models import User
from app.db.session import get_db
from app.schemas import LoginIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_LOGIN_FAIL = 5
LOCK_SECONDS = 600  # 10 分钟

_redis = None
try:
    _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
except Exception:
    _redis = None


def _fail_key(username: str) -> str:
    return f"login_fail:{username}"


def _fail_count(username: str) -> int:
    if _redis is None:
        return 0
    try:
        v = _redis.get(_fail_key(username))
        return int(v) if v else 0
    except Exception:
        return 0


def _incr_fail(username: str) -> None:
    if _redis is None:
        return
    try:
        key = _fail_key(username)
        _redis.incr(key)
        _redis.expire(key, LOCK_SECONDS)
    except Exception:
        pass


def _clear_fail(username: str) -> None:
    if _redis is None:
        return
    try:
        _redis.delete(_fail_key(username))
    except Exception:
        pass


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    if _fail_count(data.username) >= MAX_LOGIN_FAIL:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="登录失败次数过多，请10分钟后再试")

    user = db.query(User).filter(User.username == data.username).first()
    if user is None or not verify_password(data.password, user.password_hash):
        _incr_fail(data.username)
        record_audit(db, None, "login_failed", "auth", detail={"username": data.username})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")

    _clear_fail(data.username)
    record_audit(db, user, "login", "auth")
    token = create_access_token(user.id, user.role)
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)
