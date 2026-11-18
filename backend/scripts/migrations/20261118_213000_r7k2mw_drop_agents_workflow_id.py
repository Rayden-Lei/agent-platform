"""迁移（docs/15 D-12 决策 A，2026-11-18）：删掉 agents.workflow_id 这个空接线。

改什么
------
1. 预览：报告 agents 总行数、workflow_id 非空的行数（要人确认确实没有绑定）、列与外键当前是否存在。
2. `--apply`：先 DROP CONSTRAINT IF EXISTS agents_workflow_id_fkey，再 DROP COLUMN IF EXISTS workflow_id。

为什么
------
"关联工作流（预留）"是典型的不起作用的配置：列能存、详情页会回显，但**对话链路从不读它** ——
`app/runtime/agent_config.py` 原注释就写着"预留字段，对话不使用"。docs/15 D-12 定为方案 A：
界面上不该有改了也不起作用的配置；等 WF-13 以"工具类型 workflow"的方式正式接入工作流时，
再按工具的方式重新建模，而不是留一个半截字段。

实测（本机共享库）：agents 共 2 行，workflow_id 非空 0 行；agent_versions 里 7 份快照的
workflow_id 键全为 null。所以删列不丢任何绑定关系。

影响
----
- 接口契约一次切换（docs/05 铁律 6）：`AgentIn` / `AgentOut` / `AgentDetailOut` 去掉
  workflow_id 与详情里的 workflow 关联对象；再传 workflow_id 的请求按 pydantic 的默认行为
  被忽略（AgentIn 未开 extra=forbid），不会 500。
- 工作流详情 `GET /workflows/{id}` 不再返回 `agents`（那份清单就是按这一列查的）。
- `DELETE /workflows/{id}` 不再有"被智能体引用则 409"：工作流与智能体之间只剩
  runs / conversations / scheduled_jobs 三类 CASCADE 关系，删工作流照样带走它们。
- 历史发布快照里的 `workflow_id` 键**不清理**：快照是不可变历史（docs/15 3.2），
  读取侧 `runtime.agent_config.normalize_snapshot` 已不再产出这个键，比较与恢复都不受影响。
- 部署顺序：本脚本 / Alembic revision 与代码切换要落在同一个窗口（删列是不兼容变更，
  docs/08 4.4 第 2 条）。先执行 DDL 再部署新代码时，旧代码会因为 ORM 映射的列不存在而报错，
  所以必须先下线旧代码或与部署同批执行。

执行后必做
----------
- 无缓存要清。
- 确认代码已切到不带 workflow_id 的版本（`GET /agents/{id}` 的响应里不该再有这个字段）。
- docs/03-数据库设计.md 的 agents 表与快照字段清单需要同批订正（文档另有人维护，本脚本不动文档）。

幂等
----
- DROP CONSTRAINT IF EXISTS / DROP COLUMN IF EXISTS：列已不存在时是空操作，重复执行第二次 0 行变更。
- Alembic 侧同样按版本号只跑一次，upgrade 里也包了 IF EXISTS 以容忍"手工删过列、版本号还没打上"。

执行：cd backend && .venv/bin/python scripts/migrations/20261118_213000_r7k2mw_drop_agents_workflow_id.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261118_213000_r7k2mw_drop_agents_workflow_id.py --apply    # 删外键 + 删列
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

COLUMN = "workflow_id"
TABLE = "agents"
CONSTRAINT = "agents_workflow_id_fkey"
DDL = [
    f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}",
    f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {COLUMN}",
]


def _column_exists(conn) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"
    ), {"t": TABLE, "c": COLUMN}).first() is not None


def _constraint_exists(conn) -> bool:
    return conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": CONSTRAINT}).first() is not None


def _bound(conn) -> list[dict]:
    """workflow_id 非空的智能体（正常情况下是空列表：这一列从建表起就没被对话链路用过）。"""
    rows = conn.execute(text(f"SELECT id, name, {COLUMN} FROM {TABLE} WHERE {COLUMN} IS NOT NULL ORDER BY id")).mappings()
    return [dict(r) for r in rows]


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        has_column = _column_exists(conn)
        has_constraint = _constraint_exists(conn)
        total = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar()
        bound = _bound(conn) if has_column else []
        print(f"{TABLE} 共 {total} 行；{COLUMN} 列存在：{has_column}；外键 {CONSTRAINT} 存在：{has_constraint}")
        print("已绑定工作流的智能体：", [f"{b['id']}「{b['name']}」→ workflow_id={b[COLUMN]}" for b in bound] or "无")
        if not has_column:
            print(f"{COLUMN} 列已不存在，无需执行")
            return
        if bound:
            print(f"注意：有 {len(bound)} 个智能体仍绑着工作流，删列会丢掉这层绑定关系（对话链路本来就不使用它）")
        if not apply:
            print("预览：将执行")
            for statement in DDL:
                print(f"  {statement}")
            print("确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        print(f"已执行：删外键 {CONSTRAINT}、删列 {TABLE}.{COLUMN}")


if __name__ == "__main__":
    main()
