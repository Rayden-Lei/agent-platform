from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# TCP keepalive（libpq 参数）：连接池里的空闲连接每 30 秒发一次探测，NAT / 防火墙就不会悄悄回收映射。
# 2026-10-05 前没开：经 NAT 连共享库时，池里闲置几分钟的连接被中间设备丢掉，pre_ping 发现后重连，
# 但旧连接的断开包到不了服务端，服务端按自己的 tcp_keepalives_idle（7200 秒）留着它——本机后端开着时约每分钟多一个孤儿连接，
# 两小时攒了 70 多个，逼近 max_connections=100，新连接开始超时。探测 3 次（10 秒间隔）没回应即判死，坏连接一分钟内暴露。
_KEEPALIVE = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True, connect_args=_KEEPALIVE)
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
