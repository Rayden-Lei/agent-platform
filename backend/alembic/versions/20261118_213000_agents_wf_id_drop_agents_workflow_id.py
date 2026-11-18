"""drop_agents_workflow_id

Revision ID: 20261118_213000_agents_wf_id
Revises: 20261118_120000_share_quota
Create Date: 2026-11-18 21:30:00

改什么
------
1. DROP CONSTRAINT IF EXISTS agents_workflow_id_fkey（FK workflows ON DELETE RESTRICT）。
2. DROP COLUMN IF EXISTS agents.workflow_id。

为什么
------
docs/15 D-12 决策 A："关联工作流（预留）"是改了也不起作用的配置 —— 列能存、详情页会回显，
但对话链路从不读它（`app/runtime/agent_config.py` 原注释："预留字段，对话不使用"）。
D-12 定的是一次切换、不留兼容层：界面上不该有这种配置，等 WF-13 以"工具类型 workflow"
正式接入工作流时，再按工具的方式重新建模，而不是留一个半截字段。

实测（2026-11-18，本机共享库）：agents 共 2 行，workflow_id 非空 0 行；
agent_versions 里 7 份快照的 workflow_id 键全为 null。删列不丢任何绑定关系。

影响
----
- 接口契约一次切换（docs/05 铁律 6）：AgentIn / AgentOut / AgentDetailOut 去掉 workflow_id
  与详情里的 workflow 关联对象；工作流详情不再返回 agents 清单；
  DELETE /workflows/{id} 不再有"被智能体引用则 409"。
- 历史发布快照里的 workflow_id 键不清理：快照是不可变历史，读取侧 normalize_snapshot
  已不再产出这个键，比较与恢复都不受影响。
- 不删任何业务数据（该列全为 NULL，已实测）。
- 删列是不兼容变更：本 revision 与代码切换要落在同一个窗口（docs/08 4.4 第 2 条）。

执行后必做
----------
- 无缓存要清。
- 确认代码已切到不带 workflow_id 的版本（GET /agents/{id} 响应里不该再有该字段）。
- docs/03-数据库设计.md 的 agents 表与快照字段清单需同批订正（文档另有人维护，本迁移不动文档）。

幂等
----
- DROP CONSTRAINT IF EXISTS / DROP COLUMN IF EXISTS：列或约束已不存在时是空操作；
  Alembic 本身按版本号只跑一次，这里再包一层是为了容忍"手工删过、版本号还没打上"的半完成状态。
- 与手写脚本 scripts/migrations/20261118_213000_r7k2mw_drop_agents_workflow_id.py 做同一件事，
  两条通道先跑哪个都不会冲突（都带 IF EXISTS）。

执行：cd backend && ENV_FILE=.env.local .venv/bin/alembic upgrade head
"""
from typing import Sequence, Union

from alembic import op

# revision id 必须 ≤32 字符：alembic_version.version_num 是 VARCHAR(32)
revision: str = "20261118_213000_agents_wf_id"
down_revision: Union[str, Sequence[str], None] = "20261118_120000_share_quota"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 删列同样要抢表锁：与加列 / 建索引同一口径，先给锁等待设上限，
    # 拿不到锁直接失败，而不是把查 agents 的请求全堵在这条 DDL 后面（docs/08 第 4 节）。
    op.execute("SET lock_timeout = '5s'")
    # 先删外键再删列：DROP COLUMN 本会连带删除依赖它的约束，
    # 显式写出来是为了让 downgrade 的重建顺序与这里一一对应，也便于 --sql 离线模式看清动了什么。
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_workflow_id_fkey")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS workflow_id")


def downgrade() -> None:
    """重建列与外键（结构可还原，绑定关系还原不了 —— 删列时该列全为 NULL，本来就没有数据可丢）。

    不写成 raise 是照 f73a04da9cec（drop_workflow_nodes）的做法：结构足够简单，
    重建是安全的；留空 pass 才是最坏情况（执行者以为退回去了，实际结构没变）。
    """
    op.execute("SET lock_timeout = '5s'")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS workflow_id bigint")
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT agents_workflow_id_fkey "
        "FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE RESTRICT"
    )
