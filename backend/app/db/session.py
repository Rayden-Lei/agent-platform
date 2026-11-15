from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# TCP keepalive（libpq 参数）：连接池里的空闲连接每 30 秒发一次探测，NAT / 防火墙就不会悄悄回收映射。
# 2026-10-05 前没开：经 NAT 连共享库时，池里闲置几分钟的连接被中间设备丢掉，pre_ping 发现后重连，
# 但旧连接的断开包到不了服务端，服务端按自己的 tcp_keepalives_idle（7200 秒）留着它——本机后端开着时约每分钟多一个孤儿连接，
# 两小时攒了 70 多个，逼近 max_connections=100，新连接开始超时。探测 3 次（10 秒间隔）没回应即判死，坏连接一分钟内暴露。
_KEEPALIVE = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}

# 连接池显式配置。以前不写就是 SQLAlchemy 默认 pool_size=5 / max_overflow=10（共 15），
# 而检索路径最坏情况要几十个会话：chat_service._retrieve_all 最多 8 个 (库,查询) 任务并行，
# 每个任务内部的 retriever._collect_candidates 又按关键词数各开一个 SessionLocal（最多 8），
# 注释里自己写着「64 路 DB 连接」。_RETRIEVAL_SLOTS 只压住了任务数，压不住任务内部的线程数；
# 再加上入库流水线、摘要线程、调度线程各持会话，峰值轻松超过 15 → pool_timeout 30 秒后抛
# QueuePool limit reached，表现为与业务无关的 500 或首字节抖动。
#
# 取 30 上限（5 个连接 + 25 溢出）是折中：PostgreSQL 默认 max_connections=100，
# 本机后端 + 云端后端 + 运维连接要共处，不能只顾一个进程。真正的解法是减小并发需求，
# 这里先把「配置与需求明显不符」补齐，并把 pool_timeout 降到 10 秒让故障更快暴露。
DB_POOL_SIZE = 5
DB_MAX_OVERFLOW = 25
DB_POOL_TIMEOUT = 10

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    connect_args=_KEEPALIVE,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def rows_to_dict(rows) -> dict:
    """两列结果集 [(key, value), ...] → {key: value}。

    为什么不直接 dict(rows)：SQLAlchemy 的 Row 是"类元组"对象，Pylance 的 dict() 重载
    认不出它是 tuple（报 reportArgumentType：List[Row[Tuple[int, str]]] 不可分配给
    Iterable[list[bytes]]）。全仓有二十多处"两列查询包一层 dict()"的写法，
    在这里用下标取出后建 dict 收口一次，比每处 cast / type: ignore 干净。

    只给"两列查询"用；三列及以上显式取字段，别拿它当万能的。
    """
    return {row[0]: row[1] for row in rows}
