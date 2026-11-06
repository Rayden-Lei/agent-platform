"""测试数据回收：会话结束时按 `pytest-` 前缀 + 时间窗整组删掉本次运行产生的行。

为什么需要它
------------
用例自己写 `finally: seeded.drop(db)` 只在控制流走到 finally 时才生效。断言失败会被 pytest
捕获、finally 照常执行，但下面这些情况不会：进程被 kill、解释器崩溃、用例在造完数据后
`pytest.exit`、或 finally 里的清理自己抛错。

残留会实打实污染开发库。2026-11-05 的现场：12 个 `pytest-conv-agent-*`、24 个
`pytest-conv-model-*`、8 个 `pytest-kb-acl-*`，运行记录页的"智能体"下拉 14 项里 12 项是垃圾。

边界（对应 ~/.dsh/rules/testing.md 第五节"造数与清理"）
-------------------------------------------------------
- 限定标记：只删名字以 `pytest-` 开头的行；
- 时间窗：只删本次会话开始之后创建的；
- 表白名单：_DELETE_ORDER 里列出的表，别的一律不碰；
- 行数上限：超过 ROW_LIMIT 停下并报错，不放大误删。

真实业务数据（客服、聊天助手、minimax 等）名字不带这个前缀，碰不到。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

TEST_PREFIX = "pytest-"

# 顺序：子表在前、父表在后。agents.model_id / agents.workflow_id / 各表 created_by 都是 RESTRICT，
# 先删 agents 才能删 models / workflows / users；其余依赖（messages、document_chunks、
# agent_versions、agent_shares、run_nodes）走 ON DELETE CASCADE 自动带走。
_DELETE_ORDER: list[tuple[str, str]] = [
    ("conversations", "title"),      # 级联 messages；runs.conversation_id 置空
    ("agents", "name"),              # 级联 agent_versions / agent_shares / conversations / runs
    ("workflows", "name"),
    ("models", "name"),
    ("knowledge_bases", "name"),     # 级联 documents → document_chunks
    ("prompt_templates", "name"),
    ("scheduled_jobs", "name"),
    ("tools", "name"),              # mcp_server_id 没有外键，先于 mcp_servers 删即可
    ("skills", "name"),
    ("mcp_servers", "name"),
    ("api_keys", "name"),
    ("users", "username"),           # 最后：上面这些都 RESTRICT 到它
]

ROW_LIMIT = 2000


class CleanupAborted(RuntimeError):
    """待删行数超过上限：说明前缀命中面比预期大，停下来让人确认，不硬删。"""


def _where(column: str) -> str:
    return f'"{column}" like :prefix and created_at >= :since'


def purge_test_rows(db: Session, since: datetime) -> dict[str, int]:
    """删掉 since 之后创建、且名字以 pytest- 开头的行，返回每张表删掉的行数。

    调用方负责 commit。行数超过 ROW_LIMIT 时抛 CleanupAborted，此时一行都没删。

    **逐行删、每行一个 savepoint**。整表一条 DELETE 时，只要有一个 id 还被非测试数据引用
    （如某条真实智能体挂在一个 pytest- 模型上），PostgreSQL 会整体回滚，同表其它本可以删的
    行也一起留下。2026-11-05 实测：models 表里 2 个待删行，其中 1 个被引用，整表跳过导致
    另 1 个也残留。逐行删才能"能删的删掉、删不掉的留下"。
    """
    params = {"prefix": TEST_PREFIX + "%", "since": since}

    planned: dict[str, int] = {}
    for table, column in _DELETE_ORDER:
        sql = text(f'select count(*) from "{table}" where ' + _where(column))
        planned[table] = int(db.execute(sql, params).scalar_one())

    total = sum(planned.values())
    if total > ROW_LIMIT:
        raise CleanupAborted(
            f"待删 {total} 行超过上限 {ROW_LIMIT}：{planned}。"
            "确认前缀命中面无误后再手工处理，不自动放大删除。"
        )

    deleted: dict[str, int] = {}
    skipped = 0
    for table, column in _DELETE_ORDER:
        if not planned[table]:
            continue
        id_sql = text(f'select id from "{table}" where ' + _where(column))
        ids = [row[0] for row in db.execute(id_sql, params)]
        removed = 0
        for row_id in ids:
            savepoint = db.begin_nested()
            try:
                result = db.execute(text(f'delete from "{table}" where id = :id'), {"id": row_id})
                removed += result.rowcount
            except IntegrityError:
                # 还被非测试数据引用：保留，否则会打断真实数据的外键
                savepoint.rollback()
                skipped += 1
                continue
            savepoint.commit()
        if removed:
            deleted[table] = removed

    if skipped:
        deleted["_skipped"] = skipped
    return deleted


def purge_since(since: datetime) -> dict[str, int]:
    """独立开一个会话跑一次回收并提交。给 pytest_sessionfinish 用（那时没有现成的 session）。"""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        deleted = purge_test_rows(db, since)
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def session_start() -> datetime:
    return datetime.now(timezone.utc)
