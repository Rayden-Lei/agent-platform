"""工作流 checkpointer：把 LangGraph 的图检查点落到 Postgres（docs/15 WF-12、docs/09 第二梯队）。

为什么不再是 MemorySaver
------------------------
MemorySaver 把每个 thread 的完整 state 快照留在进程内存里，全仓没有 delete_thread。
一次运行（接口触发、定时任务、工作流对话每一轮、编辑器试运行）就多留一份快照，steps 还在追加，
并行/循环节点更大，长期运行必然 OOM；进程重启后 awaiting_review 的运行也续不上（docs/02 第 5 节）。

两套驱动并存
------------
SQLAlchemy 走 psycopg2（postgresql+psycopg2://），而 langgraph-checkpoint-postgres 用 psycopg3 直连、
只吃 libpq DSN。两者互不干扰：这里只把 SQLAlchemy 的 URL 转成 DSN，不碰 app.db.session 的 engine。

生命周期
--------
连接池是进程级资源，不能像 MemorySaver 那样做成"导出即初始化"的全局常量：
- lifespan 启动时 open_checkpointer() 建池，关闭时 close_checkpointer() 释放；
- 每条编译出来的图拿一个独立的 saver 实例（new_saver()），共用同一个池。
  为什么不共用一个 saver：saver 内部用一把 threading.Lock 串行化它的所有 SQL（每次 get_tuple/put
  都先抢这把锁），共用一个实例会让同时跑的多个工作流在检查点读写上互相排队；每图一个实例后，
  锁只保护单条图的操作，真正的并发度由池的连接数兜住。
"""
import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    DeltaChannelHistory,
)
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.base import MIGRATIONS
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

# 与 app/db/session.py 同一套 TCP keepalive：池里闲置的连接被 NAT / 防火墙悄悄回收后，
# 旧连接的断开包到不了服务端，服务端按自己的 tcp_keepalives_idle（7200 秒）留着它，
# 于是 checkpoint 这条路径也会攒孤儿连接。探测 3 次（10 秒间隔）没回应即判死。
_KEEPALIVE = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}


def libpq_dsn(url: str) -> str:
    """SQLAlchemy 的数据库 URL → libpq DSN（psycopg3 直连用）。

    只去掉 driver 后缀（postgresql+psycopg2:// → postgresql://），账号、口令、库名与 query 参数原样保留。
    不用正则/字符串替换拼串：口令和库名会被 SQLAlchemy 做百分号编码（如 @ → %40），
    拼串时手工解码会漏掉一部分转义，结果连不上库且报错信息看不出原因。交给 urlsplit/urlunsplit 拆装最稳。
    """
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0]
    if scheme not in ("postgresql", "postgres"):
        # 换成别的库不是本模块能处理的：saver 只支持 Postgres，配错要在启动时立刻暴露，不留到运行工作流才报
        raise ValueError(f"checkpointer 只支持 Postgres，DATABASE_URL 的协议是 {parts.scheme!r}")
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


class DualModeSaver(PostgresSaver):
    """同时提供同步与异步接口的 PostgresSaver。

    为什么需要：两条执行路径共用同一份图定义，但一条同步、一条异步 ——
    workflow_service.execute_workflow（接口触发的线程池、定时任务的调度线程）与编辑器试运行走 graph.invoke，
    chat_runner.stream_workflow（工作流对话）走 graph.astream。langgraph 基类的 aget_tuple / aput /
    aput_writes / alist / adelete_thread 默认直接 raise NotImplementedError，而 PostgresSaver 只实现了同步版，
    异步路径一跑就 NotImplementedError（实测确认，见 tests/test_checkpoint_persistence.py）。

    异步接口一律委托到线程池里的同步实现：psycopg 的同步连接在事件循环里直接调用会阻塞整个循环，
    而 to_thread 只是换了执行线程，读写语义与同步路径完全一致（同一个 saver、同一把锁）。
    """

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        # 列表类接口不在执行热路径上（只服务 get_state_history 这类排查场景），一次取全再逐个产出，
        # 不为了流式去改 PostgresSaver 内部的游标生命周期
        items = await asyncio.to_thread(lambda: list(self.list(config, filter=filter, before=before, limit=limit)))
        for item in items:
            yield item

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, str(thread_id))

    async def aget_delta_channel_history(
        self, *, config: RunnableConfig, channels: Sequence[str]
    ) -> dict[str, DeltaChannelHistory]:
        # 本仓库的 WorkflowState 没有 DeltaChannel，这条路径当前走不到；补上是为了基类契约完整，
        # 将来图状态里引入 DeltaChannel 时不会在异步路径上凭空 NotImplementedError
        return await asyncio.to_thread(self.get_delta_channel_history, config=config, channels=channels)


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _build_pool() -> ConnectionPool:
    """建连接池。autocommit + prepare_threshold=0 是 langgraph-checkpoint-postgres 的硬要求
    （迁移里有 CREATE INDEX CONCURRENTLY），取值与包的 from_conn_string 一致。"""
    return ConnectionPool(
        conninfo=libpq_dsn(settings.DATABASE_URL),
        min_size=1,
        max_size=settings.CHECKPOINT_POOL_MAX_SIZE,
        timeout=settings.CHECKPOINT_POOL_TIMEOUT,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            **_KEEPALIVE,
        },
        # 池按需建连接，启动时只建 min_size 个：不为空闲的 checkpoint 预留一堆数据库连接
        open=False,
    )


def open_checkpointer() -> None:
    """建池（幂等）。lifespan 启动时调用一次；脚本/测试里首次用到时也会懒调用。

    只探活、不建表：生产不在启动路径做 DDL，checkpoint 表由迁移脚本
    scripts/migrations/20261115_120000_c4k9xp_workflow_checkpoints.py 负责。
    表缺失时这里留一条能直接照着执行的 ERROR —— 否则表现是"每次运行工作流都 500"，
    排查要从 workflow_service 一路翻到这里才知道是没跑迁移。
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            return
        pool = _build_pool()
        pool.open(wait=True, timeout=settings.CHECKPOINT_POOL_TIMEOUT)
        try:
            with pool.connection() as conn:
                conn.execute("SELECT 1 FROM checkpoints LIMIT 1").fetchall()
        except Exception:
            # 不在这里抛：迁移没跑不该让整个平台起不来（工作流之外的功能都正常），
            # 但必须把"怎么修"说清楚；后续运行工作流会拿到明确的 UndefinedTable
            logger.error(
                "checkpoint 表不可用，工作流将无法运行。请先执行迁移：cd backend && "
                ".venv/bin/python scripts/migrations/20261115_120000_c4k9xp_workflow_checkpoints.py --apply",
                exc_info=True,
            )
        _pool = pool


def close_checkpointer() -> None:
    """释放连接池（幂等）。lifespan 关闭时调用，进程退出前不留半开连接。"""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close()


def _require_pool() -> ConnectionPool:
    open_checkpointer()
    pool = _pool
    if pool is None:  # pragma: no cover - open_checkpointer 成功时不可能为 None
        raise RuntimeError("checkpointer 连接池未初始化")
    return pool


def new_saver() -> DualModeSaver:
    """为一条编译出来的图新建 saver 实例（共用进程级连接池，各自一把锁，互不排队）。"""
    return DualModeSaver(_require_pool())


def delete_thread(thread_id: str) -> None:
    """删掉一个 thread 的全部 checkpoint / blobs / writes。

    工作流进入终态（success / failed / cancelled）后清理，否则每个 thread 会永久留一份完整历史。
    **awaiting_review 的 thread 绝不能删**：resume 要靠它找回被 interrupt 的图。
    """
    new_saver().delete_thread(str(thread_id))


def delete_thread_safely(thread_id: str) -> None:
    """终态收尾用的清理：失败只记日志，绝不向上抛。

    为什么吞掉异常：清理是"运行已经结束之后"的收尾动作。这时运行结果已经定稿（成功就是成功），
    删不掉检查点最多是行数多留一会儿，下一轮或人工清理还能补；但让它抛出去会把一次成功的运行
    变成 500，属于拿"资源回收失败"篡改"业务结果"。这里不是 `except: pass` —— 日志带 thread_id 与堆栈，
    且明确的 ERROR 级别，便于按 thread 回查。
    """
    try:
        delete_thread(thread_id)
    except Exception:
        logger.exception("检查点清理失败（不影响运行结果）thread_id=%s", thread_id)


def apply_migrations(conn: Connection) -> list[int]:
    """在给定连接上补齐 checkpoint 表，返回本次新应用的迁移版本号（给迁移脚本用）。

    直接复用 langgraph-checkpoint-postgres 自带的 MIGRATIONS 与它自己的版本记账表
    （checkpoint_migrations），不手抄一份 DDL：手抄的副本一定会与包内定义漂移，包升级后新增的迁移
    也不能靠这份脚本补齐。连接必须 autocommit —— 迁移里有 CREATE INDEX CONCURRENTLY，
    包在事务里会直接报错。
    """
    applied: list[int] = []
    cur = conn.cursor()
    cur.execute(MIGRATIONS[0])
    row = cur.execute("SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1").fetchone()
    version = -1 if row is None else int(row["v"])
    for v in range(version + 1, len(MIGRATIONS)):
        cur.execute(MIGRATIONS[v])
        cur.execute("INSERT INTO checkpoint_migrations (v) VALUES (%s)", (v,))
        applied.append(v)
    return applied
