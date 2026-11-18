"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

改什么：<新增/修改哪些表、列、索引、约束>
为什么：<对应需求或缺陷；为什么必须动结构而不是改代码>
影响：<影响哪些接口/页面；是否需要回填数据；对存量数据是否有破坏>
幂等：<重复执行是否安全；Alembic 按版本号只跑一次，upgrade 里仍要避免 DDL 冲突>
执行：cd backend && ENV_FILE=.env.local .venv/bin/alembic upgrade head
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
# revision id 必须 ≤32 字符：alembic_version.version_num 是 VARCHAR(32)，超长会在写版本行时抛
# StringDataRightTruncation —— 那时 DDL 已经执行、版本行却没写进去，下次 upgrade 会重复跑。
# 生成后如果超长，手工改短并同步改文件名（alembic 的 revision 常量与文件名不必一致）。
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    # 加列 / 建索引要抢表锁：与 scripts/migrations 里的历史脚本同一口径，先给锁等待设上限，
    # 拿不到锁直接失败，而不是把查 documents 的请求全堵在这条 DDL 后面（docs/08 第 4 节）。
    # 注意：CREATE INDEX CONCURRENTLY 不能在事务里跑，那种脚本要显式 autocommit 并自行处理。
    op.execute("SET lock_timeout = '5s'")
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
