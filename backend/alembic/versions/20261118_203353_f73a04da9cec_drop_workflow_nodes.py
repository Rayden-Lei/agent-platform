"""drop_workflow_nodes

Revision ID: f73a04da9cec
Revises: 20261118_000000_baseline
Create Date: 2026-11-18 20:33:53.233872

改什么
------
DROP TABLE workflow_nodes（连带它的主键、workflow_id 索引与外键约束）。

为什么
------
2026-11-18 死代码审计确认：这张表在生产路径与测试里都是**零引用**。
- 全仓搜索 `WorkflowNode` / `workflow_nodes`：只剩模型定义、一条级联删除注释、
  一个历史迁移里的外键条目，没有任何查询、写入或 ORM 关系。
- 画布位置（节点坐标）实际存在 `workflows.graph` 的 JSON 里 —— 前端保存与读取都走 graph，
  这张表从建表起就没被写过。
- 实测共享库 `SELECT count(*) FROM workflow_nodes` = 0，没有需要保留或迁移的数据。

留着它的代价是实打实的：一张永远为空、永远没人读的表会让人以为"节点另有存储"，
进而去改它而不是改 graph；docs/03 也要一直维护一段"未使用"的说明。
models.py 里的 `WorkflowNode` 类同批删除（docs/05 铁律「不留死代码」）。

影响
----
- 无接口、无页面、无任务受影响：没有任何代码路径读写这张表。
- 不删任何业务数据（表内 0 行，已实测）。
- 回滚需要重建表，downgrade 里写全了结构（见下），但**重建出来的是空表**，
  历史数据不存在也不可能有。
- 与本次改动同批的代码改动：`app/db/models.py` 删类、`app/runtime/workflow_config.py`
  与 `app/services/workflow_service.py` 的注释去掉 workflow_nodes 字样。

执行后必做
----------
- 无缓存要清。
- 确认代码已部署到同一版本（旧代码里没有任何读它的地方，所以部署顺序不敏感）。
- `docs/03-数据库设计.md` 的 ER 图与 3.10 节需要去掉这张表（文档另有人订正，本迁移不动文档）。

幂等
----
- `DROP TABLE IF EXISTS`：表已不存在时是空操作，重复执行无副作用。
- Alembic 本身按版本号只跑一次；这里再包一层 IF EXISTS 是为了容忍"手工删过表、
  版本号还没打上"这种半完成状态。

执行：cd backend && ENV_FILE=.env.local .venv/bin/alembic upgrade head
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f73a04da9cec'
down_revision: Union[str, Sequence[str], None] = '20261118_000000_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 删表同样要抢表锁：与建表 / 加列同一口径，先给锁等待设上限，
    # 拿不到锁直接失败，而不是把查 workflows 的请求全堵在这条 DDL 后面（docs/08 第 4 节）。
    op.execute("SET lock_timeout = '5s'")
    # 先删外键与索引再删表：DROP TABLE 本会连带删除，显式写出来是为了让 downgrade 的
    # 重建结构与这里一一对应，也便于在 `--sql` 离线模式下看清到底动了什么。
    op.execute("DROP TABLE IF EXISTS workflow_nodes")


def downgrade() -> None:
    """重建空表（结构与 models.py 删除前一致）。

    注意：只能还原结构，还原不了数据 —— 表本来就是空的，没有数据可丢。
    不写成 raise 是因为这张表的结构足够简单，重建是安全的；留一个空 pass 才是最坏情况
    （执行者以为退回去了，实际结构没变，docs/03 第 7.2 节）。
    """
    op.create_table(
        "workflow_nodes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.BigInteger(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pos_x", sa.Float(), nullable=False),
        sa.Column("pos_y", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_nodes_workflow_id", "workflow_nodes", ["workflow_id"])
