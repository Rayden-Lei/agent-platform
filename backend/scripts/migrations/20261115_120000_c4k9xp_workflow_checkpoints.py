"""迁移（2026-11-15）：工作流 checkpointer 从进程内 MemorySaver 换成 Postgres 持久化。

改什么
------
建 langgraph-checkpoint-postgres 需要的 4 张表 + 3 个索引（包内自带 DDL，本脚本只负责按幂等方式应用）：
- checkpoint_migrations：迁移版本记账（包自己的版本号表）
- checkpoints：每个 thread 每个超步一行（thread_id, checkpoint_ns, checkpoint_id 主键）
- checkpoint_blobs：channel 的值（被多处引用的 state 分片）
- checkpoint_writes：待提交的写入（interrupt 挂起时的中间结果）

为什么
------
改造前 backend/app/workflow/engine.py 是模块级 MemorySaver()：每跑一次工作流（接口触发、定时任务、
工作流对话每一轮、编辑器试运行）就在进程内存里永久留一份完整 state 快照，全仓没有 delete_thread。
steps 还在追加、并行/循环节点更大，长期运行必然 OOM；进程重启后 awaiting_review 的运行也再也续不上
（docs/02 第 5 节、docs/15 WF-12、docs/09 第二梯队"Postgres checkpointer"）。

影响
----
- 结构：新增 4 张表、3 个索引（都在 public schema，与业务表不冲突）。
- 数据：不改任何存量数据。上线瞬间 in-memory 的检查点全部丢失（本来重启也会丢），
  即发布前处于 awaiting_review 的运行无法续跑，需要重新发起。**建议在无人审批的窗口发布。**
- 执行后：无需重启（表名固定、应用按需连）。但确认依赖已安装：
  backend/requirements.txt 新增 langgraph-checkpoint-postgres==3.2.1 与 psycopg[binary]。
  云端 ap-deploy 在 requirements.txt 变化时会自动 pip install。

注意：不抄包里的 DDL，直接 import langgraph-checkpoint-postgres 的 MIGRATIONS 逐条执行。
手抄一份的结果是：包升级后新增的迁移无人应用，而表结构已经比包认识的旧 —— 这类漂移只在运行时炸。

执行
----
    cd backend && .venv/bin/python scripts/migrations/20261115_120000_c4k9xp_workflow_checkpoints.py            # 预览
    cd backend && .venv/bin/python scripts/migrations/20261115_120000_c4k9xp_workflow_checkpoints.py --apply    # 执行

幂等：表用 IF NOT EXISTS；已应用的版本记在 checkpoint_migrations 里跳过。重复执行第二次影响 0 行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from psycopg import connect
from psycopg.rows import dict_row

from app.config import settings
from app.workflow.checkpointer import apply_migrations, libpq_dsn
from langgraph.checkpoint.postgres.base import MIGRATIONS

TABLES = ("checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes")


def _existing(conn) -> dict[str, bool]:
    """按当前 search_path 判断表在不在。用 to_regclass 而不是写死 public：
    包内 DDL 的表名都不带 schema 前缀，落在哪里由 search_path 决定，检查口径必须与 DDL 一致。"""
    present = {row["t"]: row["exists"] for row in conn.execute(
        "SELECT t, to_regclass(t) IS NOT NULL AS exists FROM unnest(%s::text[]) AS t", (list(TABLES),),
    ).fetchall()}
    return present


def main() -> None:
    apply = "--apply" in sys.argv
    # 迁移里有 CREATE INDEX CONCURRENTLY，必须 autocommit；row_factory 只是为了与 saver 的取值一致
    with connect(libpq_dsn(settings.DATABASE_URL), autocommit=True, row_factory=dict_row,
                 connect_timeout=10) as conn:
        conn.execute("SET lock_timeout = '5s'")
        exists = _existing(conn)
        for table, present in exists.items():
            print(f"{table}：{'已存在' if present else '待建'}")

        # checkpoint_migrations 不存在时不能查它（UndefinedTable），先看 to_regclass
        version = -1
        if exists["checkpoint_migrations"]:
            row = conn.execute("SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1").fetchone()
            version = -1 if row is None else int(row["v"])
        pending = list(range(version + 1, len(MIGRATIONS)))
        print(f"包内迁移共 {len(MIGRATIONS)} 条，当前库已应用到 v{version}，待应用 {len(pending)} 条：{pending}")

        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return

        applied = apply_migrations(conn)
        print(f"已应用迁移版本：{applied}" if applied else "无需应用，库已是最新")
        exists = _existing(conn)
        missing = [t for t, present in exists.items() if not present]
        if missing:
            # 走到这里说明 DDL 没生效：与其让运行时第一次跑工作流才 500，不如现在就让迁移失败
            raise SystemExit(f"中止：以下表在迁移后仍不存在 {missing}")
        indexes = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY(%s) ORDER BY 1",
            (list(TABLES),),
        ).fetchall()
        print("索引：" + ", ".join(r["indexname"] for r in indexes))


if __name__ == "__main__":
    main()
