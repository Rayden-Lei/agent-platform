"""share_quota_usage：分享每日额度改为数据库原子扣减（2026-11-18）。

改什么
------
新建表 `share_quota_usage`（含唯一约束 `uq_share_quota_usage_share_day_visitor` 与 `share_id` 索引）。

为什么
------
`share_service.check_chat_quota` 原来是"先 `count(runs)` 再放行"的 check-then-act：
并发请求各自 count 到同一个未超限的数字后全部放行，**链接每日总量这个成本硬上限直接失效**。
改成数据库层原子扣减（照 `api_key_service.authenticate` 的既有范式：
`UPDATE ... WHERE used < 上限` 按影响行数判断），需要一个可按 (分享, 自然日, 访客) 定位并累加的计数行。

影响
----
- 只新增表，不改现有列、不动现有数据。
- 上线后第一天的额度从 0 开始：不回填历史 runs 的计数（旧口径按 runs 条数、新口径按放行的对话次数，
  语义已变，回填反而会造出错误的额度状态）；跨过部署当天即自然对齐。
- 随分享删除级联（ON DELETE CASCADE），删分享不留孤儿计数行。
- 历史手写脚本 `scripts/migrations/20261118_120000_q7w4zn_share_quota_usage.py` 做同样的事，
  给还没接 Alembic 的部署用；两者都是 IF NOT EXISTS，先跑哪个都不会冲突。

执行后必做
----------
重启后端（代码与表要同时到位；模型声明在 app/db/models.py 的 ShareQuotaUsage）。

幂等
----
- 建表前先查 `to_regclass`，已存在则跳过；重复执行无副作用。

执行：cd backend && ENV_FILE=.env.local .venv/bin/alembic upgrade head
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision id 必须 ≤32 字符：alembic 自建的 alembic_version.version_num 是 VARCHAR(32)，
# 超长会在写版本行时抛 StringDataRightTruncation —— DDL 已经执行了、版本行却没写进去，
# 下次 upgrade 会重复跑这条迁移（2026-11-18 实测踩到：原名 33 字符，正是这个失败）。
revision: str = "20261118_120000_share_quota"
# 串在 drop_workflow_nodes 之后，保持单 head（2026-11-18 同日两条迁移由不同人并行生成，
# 原来都指向 baseline 会形成两个 head，alembic upgrade head 直接报 Multiple head revisions）。
# 两条迁移互不依赖（一条建表、一条删表），先后顺序不影响结果。
down_revision: Union[str, Sequence[str], None] = "f73a04da9cec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "share_quota_usage"
CONSTRAINT = "uq_share_quota_usage_share_day_visitor"


def _table_exists(bind) -> bool:
    return bind.execute(sa.text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is not None


def upgrade() -> None:
    # 离线模式（--sql）没有连接，查不了表；照 baseline 的做法跳过探测、直接输出 DDL，
    # 让"打印 SQL 供 review"这个用途可用。在线模式下的幂等探测照常生效。
    if not op.get_context().as_sql and _table_exists(op.get_bind()):
        # 已由手写脚本（scripts/migrations/20261118_120000_*）建好：跳过，保持两条通道一致
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("share_id", sa.BigInteger(), sa.ForeignKey("agent_shares.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usage_date", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("visitor_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("share_id", "usage_date", "visitor_id", name=CONSTRAINT),
    )
    op.create_index(f"ix_{TABLE}_share_id", TABLE, ["share_id"])


def downgrade() -> None:
    """可安全回退：这是本任务新增的纯计数表，代码回退后不再有人读写它。

    删表会丢掉当天的额度计数，回退到旧代码后额度改按 runs 计数，本来也不读这张表 —— 无数据损失风险。
    """
    op.drop_index(f"ix_{TABLE}_share_id", table_name=TABLE)
    op.drop_table(TABLE)
