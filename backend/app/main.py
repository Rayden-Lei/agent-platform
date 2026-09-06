import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.exceptions import BizError
from app.core.ip_filter import IpFilterMiddleware
from app.core.middleware import RequestContextMiddleware
from app.core.request_context import REQUEST_ID_HEADER, RequestIdFilter, get_request_id
from app.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.rag.embeddings import embedding_status

logger = logging.getLogger(__name__)

_DB_INIT_RETRIES = 30
_DB_INIT_INTERVAL_SECONDS = 2


def _init_db() -> None:
    """等待数据库就绪，启用 vector 扩展，建表并初始化默认管理员（幂等）。"""
    for attempt in range(1, _DB_INIT_RETRIES + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
            Base.metadata.create_all(engine)
            break
        except Exception as e:
            if attempt == _DB_INIT_RETRIES:
                logger.exception("数据库初始化失败，已重试 %d 次，放弃启动", _DB_INIT_RETRIES)
                raise
            # 容器编排下数据库常晚于应用就绪，等待属正常现象，但要能看出等了多久
            logger.warning("数据库尚未就绪（第 %d/%d 次重试）：%s", attempt, _DB_INIT_RETRIES, e)
            time.sleep(_DB_INIT_INTERVAL_SECONDS)

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
    """应用启动/关闭钩子：初始化数据库 → 检查向量后端是否降级（降级则告警）→ 启动定时调度器。"""
    _init_db()
    status = embedding_status()
    if status["mode"] != "model":
        # 启动即暴露降级：否则"检索不准"要排查很久才发现根本没在用向量模型
        logger.warning("向量检索处于降级状态：%s", status["reason"])
    from app.core.scheduler import get_scheduler
    get_scheduler()
    if settings.INGEST_AUTO_RESUME:
        # 上次进程被杀时处理到一半的文档（只认本机的）自动续处理，不用等人去点
        import threading
        from app.rag.pipeline import process_document, resume_stalled_documents
        resume_stalled_documents(lambda doc_id: threading.Thread(target=process_document, args=(doc_id, True), name=f"resume-{doc_id}", daemon=True).start())
    yield


def _configure_logging() -> None:
    """统一日志配置：每条日志带 request_id，便于把一次请求的全部日志聚合起来。

    uvicorn 只给自己的 logger 配 handler，应用侧 logger 的 INFO/ERROR 否则会被丢掉。
    basicConfig 在 root 已有 handler 时不生效，因此不会覆盖 pytest 等外部环境的配置；
    filter 挂到每个已存在的 handler 上，格式里的 %(request_id)s 才不会因缺字段报错。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
    )
    request_id_filter = RequestIdFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(request_id_filter)


_configure_logging()

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
# 中间件顺序（后 add 的在外层）：IP 黑名单 → CORS → 请求 ID。
# 黑名单放在 CORS 内层，403 才会带跨域头；请求 ID 放最外层，CORS 预检与鉴权失败的响应也带追踪 ID。
app.add_middleware(IpFilterMiddleware)
# 跨域按白名单放行（CORS_ORIGINS）：浏览器直连后端时才需要，经同源反代不涉及。
# allow_credentials=True 时浏览器不接受通配符 *，所以必须是明确的源列表
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


def _trace_id(request) -> str:
    """取本次请求的追踪 ID。

    未处理异常的 handler 由更外层的 ServerErrorMiddleware 调用，此时中间件已重置 contextvar，
    只能从 scope 里取；正常路径两者取到的是同一个值。
    """
    return getattr(request.state, "request_id", None) or get_request_id()


@app.exception_handler(BizError)
async def biz_error_handler(request, exc: BizError):
    """业务异常 → 统一错误响应 {"detail": ..., "trace_id": ...}。

    业务失败是预期内的（校验不通过、状态不允许），记 INFO 不记堆栈；只有故障才值得 ERROR。
    """
    logger.info("业务异常 %s %s status=%s detail=%s", request.method, request.url.path, exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "trace_id": _trace_id(request)},
        headers=exc.headers,  # 429 的 Retry-After / X-RateLimit-* 由此透传
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request, exc: StarletteHTTPException):
    """鉴权/路由类错误：保持 {"detail": ...} 契约不变，补上 trace_id 与原有响应头。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "trace_id": _trace_id(request)},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request, exc: Exception):
    """兜底：任何未处理异常都留完整堆栈，对外只给可读信息与追踪 ID，不泄漏内部细节。"""
    trace_id = _trace_id(request)
    logger.exception("未处理异常 %s %s trace_id=%s", request.method, request.url.path, trace_id)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请携带 trace_id 联系管理员", "trace_id": trace_id},
        # 这条响应不经过请求 ID 中间件的 send 包装（异常已冒泡出去），响应头要在这里补
        headers={REQUEST_ID_HEADER: trace_id},
    )


@app.get("/health")
def health():
    """探活：不查库，只报进程状态与向量后端模式（mode=hash 表示检索已降级）。"""
    status = embedding_status()
    return {"status": "ok", "app": settings.APP_NAME, "embedding_mode": status["mode"]}