import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.exceptions import BizError
from app.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine


def _init_db() -> None:
    """等待数据库就绪，启用 vector 扩展，建表并初始化默认管理员（幂等）。"""
    for attempt in range(30):
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
            Base.metadata.create_all(engine)
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(2)

    db = SessionLocal()
    try:
        from app.core.security import hash_password
        from app.db.models import User

        if not db.query(User).filter(User.username == "admin").first():
            db.add(User(username="admin", password_hash=hash_password("admin123"), role="admin"))
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _init_db()
    from app.core.scheduler import get_scheduler
    get_scheduler()
    yield


# 最小日志配置：uvicorn 只给自己的 logger 配 handler，应用侧 logger 的 INFO/ERROR 否则会被丢掉。
# basicConfig 在 root 已有 handler 时不生效，因此不会覆盖 pytest 等外部环境的配置。
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(BizError)
async def biz_error_handler(request, exc: BizError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}