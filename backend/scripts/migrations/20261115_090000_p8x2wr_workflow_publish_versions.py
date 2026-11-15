"""迁移（docs/15 FR-075 / WF-02）：工作流草稿与发布版本分离。

改什么：
  workflow_versions  新建表：id、workflow_id → workflows ON DELETE CASCADE、version、snapshot jsonb、
                     created_at、created_by → users ON DELETE SET NULL、note varchar(200)；
                     唯一约束 (workflow_id, version)，索引 workflow_id
  workflows          ADD published_version integer、published_at timestamptz —— 线上版本指针，从未发布为空
  runs               ADD workflow_version integer —— 本次执行用的是哪一版；试跑与历史运行为空
  数据（--apply 才执行，默认只预览）：
  1. workflow_versions 回填：每个**存量**工作流按其当前 graph 生成 v1 快照（note = "迁移补发"）
  2. workflows 回填：published_version = 1、published_at = updated_at、status = 'published'
     published_at 取 updated_at 而不是 now()：updated_at 是这张图最后一次被改的时间，
     就是它事实上的上线时间。用 now() 会让所有存量版本显示同一时刻，排查"哪一版是哪天上的"时误导人。
为什么：2026-11-15 前工作流保存即上线（workflow_service.update_workflow 只做 version += 1，不留快照），
  改一次图会立刻影响已绑定的定时任务与已发出的 API 调用方，出事无法回滚。
  本特性上线后运行时只读 published_version 指向的快照，所以**存量工作流必须回填成已发布**：
  不回填的话它们全部变成"未发布"，现有定时任务与 API Key 调用会在部署瞬间全部 403。
影响：只加表、加列、加约束与索引，不改任何既有列。回填可重复执行（已有 published_version 的不再处理）。
  2026-11-15 共享库预期：1 个工作流（id=1，draft）被回填为已发布 v1；runs 里 302 条工作流运行
  的 workflow_version 保持 NULL（本特性之前的运行没有版本概念，回填 v1 是伪造审计信息）。
执行后必做：部署新代码后本脚本无需重跑（回填只处理 published_version 为空的行）。
  本机与服务器共用一个库，顺序必须是：先 --apply 本脚本（新列可空，旧代码照常工作）→ 再部署新代码。
  反过来的话，新代码读不到 published_version，会把所有工作流当成"未发布"，运行全部 403。
幂等：CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS；
  唯一约束先查是否已存在；回填按 published_version IS NULL 过滤；lock_timeout 5 秒，导入进行中拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20261115_090000_p8x2wr_workflow_publish_versions.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261115_090000_p8x2wr_workflow_publish_versions.py --apply    # 执行
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import bindparam, text

from app.db.session import engine

DDL = [
    """
    CREATE TABLE IF NOT EXISTS workflow_versions (
        id bigserial PRIMARY KEY,
        workflow_id bigint NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
        version integer NOT NULL,
        snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        created_by bigint REFERENCES users(id) ON DELETE SET NULL,
        note varchar(200)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_workflow_versions_workflow_id ON workflow_versions (workflow_id)",
    "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS published_version integer",
    "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS published_at timestamptz",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS workflow_version integer",
]
UNIQUE_VERSION = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_workflow_versions_workflow_version') THEN
    ALTER TABLE workflow_versions ADD CONSTRAINT uq_workflow_versions_workflow_version UNIQUE (workflow_id, version);
  END IF;
END $$
"""
DUPLICATE_VERSIONS = "SELECT workflow_id, version, count(*) FROM workflow_versions GROUP BY 1, 2 HAVING count(*) > 1"
BACKFILL_NOTE = "迁移补发"
BACKFILL_VERSION = 1


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"), {"t": table, "c": column}).first() is not None


def _id_filter(ids: list[int] | None, column: str = "id") -> tuple[str, dict]:
    """只处理给定 ID 的条件（用例只动自己造的数据）；None 表示全部。"""
    return (f" AND {column} IN :ids", {"ids": list(ids)}) if ids is not None else ("", {})


def plan_backfill(conn, workflow_ids: list[int] | None = None) -> list[dict]:
    """还没发布过的工作流：按当前 graph 生成 v1 快照，线上指针指向它。
    已经有 published_version 的工作流（跑过一次之后再跑）不再处理。"""
    where, params = _id_filter(workflow_ids)
    pointer = "AND published_version IS NULL" if _column_exists(conn, "workflows", "published_version") else ""
    stmt = text(f"""
        SELECT id, name, description, graph, version, updated_at, status
        FROM workflows WHERE TRUE {pointer}{where} ORDER BY id
    """)
    if workflow_ids is not None:
        stmt = stmt.bindparams(bindparam("ids", expanding=True))
    return [dict(row) for row in conn.execute(stmt, params).mappings()]


def backfill_versions(conn, workflows: list[dict]) -> int:
    """写入 v1 快照并把工作流置为已发布。已存在的 (workflow_id, 1) 不重复插入（唯一约束兜底）。"""
    filled = 0
    for w in workflows:
        exists = conn.execute(
            text("SELECT 1 FROM workflow_versions WHERE workflow_id = :w AND version = :v"),
            {"w": w["id"], "v": BACKFILL_VERSION},
        ).first()
        if exists is None:
            snapshot = {"name": w["name"], "description": w["description"], "graph": w["graph"] or {}}
            conn.execute(
                text("INSERT INTO workflow_versions (workflow_id, version, snapshot, note) VALUES (:w, :v, CAST(:s AS jsonb), :n)"),
                {"w": w["id"], "v": BACKFILL_VERSION, "s": json.dumps(snapshot, ensure_ascii=False), "n": BACKFILL_NOTE},
            )
            filled += 1
        # published_at 用 updated_at：那是这张图最后一次被改的时间，也是它事实上的上线时间。
        # 已经指向别处的（并发发布过）不覆盖 —— COALESCE 只填空值。
        conn.execute(
            text("""
                UPDATE workflows SET published_version = :v, status = 'published',
                       published_at = COALESCE(published_at, updated_at)
                WHERE id = :w
            """),
            {"w": w["id"], "v": BACKFILL_VERSION},
        )
    return filled


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        if _column_exists(conn, "workflow_versions", "id"):
            duplicates = conn.execute(text(DUPLICATE_VERSIONS)).all()
            if duplicates:
                print("workflow_versions 存在重复的 (workflow_id, version)，先人工确认怎么清理再执行：", duplicates)
                sys.exit(1)
        plans = plan_backfill(conn)
        print(f"待回填为已发布 v{BACKFILL_VERSION} 的工作流：{len(plans)} 个")
        for w in plans:
            print(f"  工作流 {w['id']}「{w['name']}」status={w['status']} version={w['version']} published_at←{w['updated_at']}")
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        conn.execute(text(UNIQUE_VERSION))
        filled = backfill_versions(conn, plan_backfill(conn))  # 列建好后重新判定：已有指针的不再处理
        print(f"已执行：workflow_versions 写入 {filled} 行、工作流置为已发布 {len(plans)} 个")
        print("runs.workflow_version 保持 NULL：本特性之前的运行没有版本概念，回填 v1 是伪造审计信息")


if __name__ == "__main__":
    main()
