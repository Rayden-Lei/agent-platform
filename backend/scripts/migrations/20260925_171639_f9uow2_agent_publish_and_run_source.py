"""迁移（docs/15 3.11 M1）：智能体发布语义与运行记录来源列。

改什么：
  agents          ADD published_version integer、published_at timestamptz —— 线上版本指针，从未发布为空
  agent_versions  ADD created_by bigint → users ON DELETE SET NULL、note varchar(200)；唯一约束 (agent_id, version)
  runs            ADD source varchar(16) NOT NULL DEFAULT 'ui'、agent_version integer、
                  api_key_id bigint → api_keys ON DELETE SET NULL、schedule_id bigint → scheduled_jobs ON DELETE SET NULL；
                  索引 (source, started_at)、(api_key_id, started_at)、(schedule_id)
  数据（--apply 才执行，默认只预览）：
  1. runs.source 回填：input.source 有值用它；对话记 chat；input.scheduled 为真记 schedule；其余 ui（当时没记，界面与 API Key 分不清）。
     只改仍是默认 'ui' 且推算值不同的行 —— 部署窗口里旧代码写入的行（列默认 'ui'）部署后再跑一次即被纠正，新代码显式写入的不受影响
  2. runs.schedule_id 回填：input.schedule_id 指向仍存在的定时任务时写入
  3. 已发布的智能体（docs/15 D-03 A）：当前行与最新快照一致 → published_version 指向它；
     不一致或没有快照 → 按当前行补发一版（note = "迁移补发"），线上行为不变。已有 published_version 的不再处理
为什么：发布原来只是存快照、对话读当前行，保存即上线，调试只能调线上；分享与 API 对外后每次保存都会改变外部调用方看到的回答。
  来源原来只在 input JSON 里：按来源筛选走不了索引，57 条早期对话运行没写 source，按"对话"筛选会漏掉它们。
影响：只加列、约束与索引；唯一约束前先查重复，有重复即停止、不自动删改。回填与补发都可重复执行，第二次 0 行。
  2026-09-25 共享库预期：补发 2 个智能体（1、150 都在最后一次发布后换过模型）；来源回填 chat 95 行（其中 57 行 input 里没写 source）、
  schedule 264 行，其余 10 行保持默认 ui。
执行后必做：部署新代码后再执行一次 --apply，纠正部署窗口里旧代码写入的来源。
  本机与服务器共用一个库，顺序必须是：先 --apply 本脚本（新列可空或有默认值，旧代码照常工作）→ 再部署新代码。
  反过来的话，新代码读不到 published_version，会把已发布的智能体当成"未发布"，对话全部 403。
幂等：ADD COLUMN / CREATE INDEX IF NOT EXISTS；约束先查是否已存在；lock_timeout 5 秒，导入进行中拿不到锁就退出。

执行：cd backend && .venv/bin/python scripts/migrations/20260925_171639_f9uow2_agent_publish_and_run_source.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20260925_171639_f9uow2_agent_publish_and_run_source.py --apply    # 执行
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import bindparam, text

from app.db.session import engine
from app.runtime.agent_config import normalize_snapshot, snapshot_of

DDL = [
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS published_version integer",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS published_at timestamptz",
    "ALTER TABLE agent_versions ADD COLUMN IF NOT EXISTS created_by bigint REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE agent_versions ADD COLUMN IF NOT EXISTS note varchar(200)",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS source varchar(16) NOT NULL DEFAULT 'ui'",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS agent_version integer",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS api_key_id bigint REFERENCES api_keys(id) ON DELETE SET NULL",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS schedule_id bigint REFERENCES scheduled_jobs(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_runs_source_started_at ON runs (source, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_runs_api_key_started_at ON runs (api_key_id, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_runs_schedule_id ON runs (schedule_id)",
]
UNIQUE_VERSION = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_agent_versions_agent_version') THEN
    ALTER TABLE agent_versions ADD CONSTRAINT uq_agent_versions_agent_version UNIQUE (agent_id, version);
  END IF;
END $$
"""
DUPLICATE_VERSIONS = "SELECT agent_id, version, count(*) FROM agent_versions GROUP BY agent_id, version HAVING count(*) > 1"
# 按 input 推算的来源：与新代码写入的取值一致
DERIVED_SOURCE = "COALESCE(input->>'source', CASE WHEN run_type = 'chat' THEN 'chat' WHEN input->>'scheduled' = 'true' THEN 'schedule' ELSE 'ui' END)"
REPUBLISH_NOTE = "迁移补发"


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"), {"t": table, "c": column}).first() is not None


def _id_filter(ids: list[int] | None, column: str = "id") -> tuple[str, dict]:
    """只处理给定 ID 的条件（用例只动自己造的数据）；None 表示全部。"""
    return (f" AND {column} IN :ids", {"ids": list(ids)}) if ids is not None else ("", {})


def source_backfill_counts(conn, run_ids: list[int] | None = None) -> list[tuple[str, int]]:
    """将被改写的来源及行数。列还不存在时（首次预览）按"全部行都是默认 ui"估算。"""
    where, params = _id_filter(run_ids)
    current = "source" if _column_exists(conn, "runs", "source") else "'ui'"
    stmt = text(f"SELECT {DERIVED_SOURCE} AS src, count(*) FROM runs WHERE {current} = 'ui' AND {DERIVED_SOURCE} <> 'ui'{where} GROUP BY 1 ORDER BY 1")
    if run_ids is not None:
        stmt = stmt.bindparams(bindparam("ids", expanding=True))
    return [(r[0], int(r[1])) for r in conn.execute(stmt, params)]


def backfill_sources(conn, run_ids: list[int] | None = None) -> int:
    where, params = _id_filter(run_ids)
    stmt = text(f"UPDATE runs SET source = {DERIVED_SOURCE} WHERE source = 'ui' AND {DERIVED_SOURCE} <> 'ui'{where}")
    if run_ids is not None:
        stmt = stmt.bindparams(bindparam("ids", expanding=True))
    return conn.execute(stmt, params).rowcount


def backfill_schedule_ids(conn, run_ids: list[int] | None = None) -> int:
    where, params = _id_filter(run_ids, "r.id")
    stmt = text(f"""
        UPDATE runs r SET schedule_id = (r.input->>'schedule_id')::bigint
        WHERE r.schedule_id IS NULL AND r.input ? 'schedule_id' AND (r.input->>'schedule_id') ~ '^[0-9]+$'
          AND EXISTS (SELECT 1 FROM scheduled_jobs s WHERE s.id = (r.input->>'schedule_id')::bigint){where}
    """)
    if run_ids is not None:
        stmt = stmt.bindparams(bindparam("ids", expanding=True))
    return conn.execute(stmt, params).rowcount


def plan_republish(conn, agent_ids: list[int] | None = None) -> list[dict]:
    """已发布但还没有线上版本指针的智能体，逐个判定：指向最新快照，还是按当前行补发一版。"""
    where, params = _id_filter(agent_ids)
    pointer = "AND published_version IS NULL" if _column_exists(conn, "agents", "published_version") else ""
    stmt = text(f"""
        SELECT id, name, description, system_prompt, model_id, params, kb_ids, tool_ids, workflow_id,
               prompt_template_id, prompt_template_version, prompt_variables, version
        FROM agents WHERE status = 'published' {pointer}{where} ORDER BY id
    """)
    if agent_ids is not None:
        stmt = stmt.bindparams(bindparam("ids", expanding=True))
    plans = []
    for row in conn.execute(stmt, params).mappings():
        latest = conn.execute(text("SELECT version, snapshot, created_at FROM agent_versions WHERE agent_id = :a ORDER BY version DESC LIMIT 1"), {"a": row["id"]}).mappings().first()
        current = snapshot_of(SimpleNamespace(**row))
        if latest is not None and normalize_snapshot(latest["snapshot"]) == current:
            plans.append({"agent_id": row["id"], "name": row["name"], "action": "point", "version": latest["version"], "published_at": latest["created_at"]})
        else:
            # 新版本号取"最新快照"与 agents.version 的较大者 + 1：早期回滚只加 agents.version 不写快照，不能复用界面上出现过的号
            next_version = max(latest["version"] if latest else 0, row["version"] or 0) + 1
            plans.append({"agent_id": row["id"], "name": row["name"], "action": "republish", "version": next_version, "snapshot": current})
    return plans


def apply_republish(conn, plans: list[dict]) -> None:
    for p in plans:
        if p["action"] == "republish":
            conn.execute(
                text("INSERT INTO agent_versions (agent_id, version, snapshot, note) VALUES (:a, :v, CAST(:s AS jsonb), :n)"),
                {"a": p["agent_id"], "v": p["version"], "s": json.dumps(p["snapshot"], ensure_ascii=False), "n": REPUBLISH_NOTE},
            )
            conn.execute(text("UPDATE agents SET version = :v, published_version = :v, published_at = now() WHERE id = :a"), {"a": p["agent_id"], "v": p["version"]})
        else:
            conn.execute(text("UPDATE agents SET published_version = :v, published_at = :t WHERE id = :a"), {"a": p["agent_id"], "v": p["version"], "t": p["published_at"]})


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        duplicates = conn.execute(text(DUPLICATE_VERSIONS)).all()
        if duplicates:
            print("agent_versions 存在重复的 (agent_id, version)，先人工确认怎么清理再执行：", duplicates)
            sys.exit(1)
        sources = source_backfill_counts(conn)
        plans = plan_republish(conn)
        print("来源回填（将改写的行数）：", sources or "无")
        for p in plans:
            what = f"按当前行补发 v{p['version']}（{REPUBLISH_NOTE}）" if p["action"] == "republish" else f"线上版本指向已有快照 v{p['version']}"
            print(f"智能体 {p['agent_id']}「{p['name']}」：{what}")
        if not plans:
            print("智能体：没有需要处理的")
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        for statement in DDL:
            conn.execute(text(statement))
        conn.execute(text(UNIQUE_VERSION))
        filled_sources = backfill_sources(conn)
        filled_schedules = backfill_schedule_ids(conn)
        apply_republish(conn, plan_republish(conn))  # 列建好后重新判定：已有指针的不再处理
        print(f"已执行：来源回填 {filled_sources} 行、schedule_id 回填 {filled_schedules} 行、智能体处理 {len(plans)} 个")


if __name__ == "__main__":
    main()
