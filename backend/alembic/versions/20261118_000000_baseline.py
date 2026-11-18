"""baseline：Alembic 接入前库里已经存在的结构（2026-11-18）。

改什么
------
不改任何结构。这条 revision 只做一件事：把"当前库的结构已经到位"记进 alembic_version，
之后的结构变更才有基线可以增量。

为什么是空迁移而不是把现有表全写进来
----------------------------------
接入前已有几十个手写脚本（scripts/migrations/）和 create_all 一起维护结构，
把它们改写成一条建表 revision 是高风险的纯重构：任何一处漏写/写歪，
在存量库上执行 upgrade 就是破坏。所以采用"基线 + 后续增量"：
- 存量库：人工执行一次 `alembic stamp head`，只写版本行，不动结构；
- 全新库：先 `setup_db.py` + 应用启动 create_all（或 init_db.py）建出结构，再 stamp head；
- 之后的每一次结构变更，都用 `alembic revision --autogenerate` 生成增量 revision。
历史脚本冻结为记录，不再新增（docs/03 第 7 节）。

影响
----
- upgrade 不改结构，只校验核心表存在：在空库上直接 `alembic upgrade head` 会明确报错并提示先建结构，
  而不是把空库静默标记成"已是最新"，之后所有增量都跳过、留下一个永远缺表的库。
- downgrade 直接拒绝：基线之前的结构不由 Alembic 管理，回退到 base 只会删掉版本行、
  留下一个 Alembic 以为"空"、实际满是表的库 —— 这种不一致比报错危险得多。

幂等
----
- 重复执行 upgrade：Alembic 见到版本行已是本 revision，直接跳过。
- stamp head 重复执行：只更新版本行，无副作用。

执行：cd backend && ENV_FILE=.env.local .venv/bin/alembic stamp head
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261118_000000_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 基线时刻的核心表：任何一个缺失都说明这个库还没有结构（新库没跑 create_all），
# 不能就这样把版本打到最新。只取各业务域的代表表，不做全量比对（全量比对是 alembic check 的事）。
_CORE_TABLES = ("users", "agents", "conversations", "runs", "knowledge_bases", "document_chunks", "llm_calls")


def upgrade() -> None:
    ctx = op.get_context()
    if ctx.as_sql:
        # 离线模式（--sql）：没有连接，查不了表。这里跳过校验并留一行注释说明，
        # 让"打印 SQL 供 review"这个用途可用；真正的防呆在在线模式下生效。
        op.execute("-- baseline: 离线模式不做核心表校验（无连接）")
        return
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
    ).scalars()
    existing = set(rows)
    missing = [t for t in _CORE_TABLES if t not in existing]
    if missing:
        raise RuntimeError(
            "基线校验失败：库里缺少核心表 " + ", ".join(missing) + "。"
            "全新库请先建结构（scripts/setup_db.py + 启动应用 create_all，或 scripts/init_db.py），"
            "再执行 alembic stamp head；不要直接 upgrade。"
        )


def downgrade() -> None:
    raise RuntimeError(
        "baseline 不负责建表/删表：回退到 base 只会删掉 alembic_version 里的版本行，"
        "留下一个 Alembic 认为为空、实际满是表的库。确需重置版本记录请人工处理 alembic_version 表。"
    )
