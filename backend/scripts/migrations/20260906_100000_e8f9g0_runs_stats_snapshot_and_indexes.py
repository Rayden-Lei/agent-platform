"""迁移：runs 增加统计快照列 model_id / conversation_id / cost，并补统计与详情页需要的索引。

改什么：
  ALTER TABLE runs ADD COLUMN model_id bigint REFERENCES models(id) ON DELETE SET NULL；
  ALTER TABLE runs ADD COLUMN conversation_id bigint REFERENCES conversations(id) ON DELETE SET NULL；
  ALTER TABLE runs ADD COLUMN cost double precision；
  CREATE INDEX runs(started_at) / runs(agent_id) / runs(workflow_id) / runs(model_id) / conversations(agent_id)；
  回填：model_id 取智能体当前绑定的模型；cost 按当前单价折算（历史单价无法还原，只回填仍为空的行）。
为什么：页面深度优化的运营统计（按天趋势、按模型聚合、工作台概览）要按 started_at 区间扫描并按模型分组；
  成本改为收尾时快照，避免改单价或智能体换模型后历史成本被重写。
影响：只加可空列与索引；回填只写 NULL 的行，重复执行为 0 行。conversation_id 不回填（历史对话运行无从关联）。
执行后必做：无。
幂等：ADD COLUMN / CREATE INDEX IF NOT EXISTS；回填带 IS NULL 条件。

执行：cd backend && .venv/bin/python scripts/migrations/20260906_100000_e8f9g0_runs_stats_snapshot_and_indexes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS model_id bigint REFERENCES models(id) ON DELETE SET NULL",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS conversation_id bigint REFERENCES conversations(id) ON DELETE SET NULL",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS cost double precision",
    "CREATE INDEX IF NOT EXISTS ix_runs_started_at ON runs (started_at)",
    "CREATE INDEX IF NOT EXISTS ix_runs_agent_id ON runs (agent_id)",
    "CREATE INDEX IF NOT EXISTS ix_runs_workflow_id ON runs (workflow_id)",
    "CREATE INDEX IF NOT EXISTS ix_runs_model_id ON runs (model_id)",
    "CREATE INDEX IF NOT EXISTS ix_conversations_agent_id ON conversations (agent_id)",
]
BACKFILL_MODEL = "UPDATE runs r SET model_id = a.model_id FROM agents a WHERE r.agent_id = a.id AND r.model_id IS NULL"
BACKFILL_COST = """
UPDATE runs r SET cost = round(((
    coalesce((r.token_usage->>'prompt_tokens')::bigint, 0) * coalesce(m.price_input, 0)
  + coalesce((r.token_usage->>'completion_tokens')::bigint, 0) * coalesce(m.price_output, 0)) / 1000000.0)::numeric, 6)
FROM models m
WHERE r.model_id = m.id AND r.cost IS NULL AND r.token_usage <> '{}'::jsonb
  AND (m.price_input IS NOT NULL OR m.price_output IS NOT NULL)
"""


def main() -> None:
    with engine.begin() as conn:
        for statement in DDL:
            conn.execute(text(statement))
        models_filled = conn.execute(text(BACKFILL_MODEL)).rowcount
        costs_filled = conn.execute(text(BACKFILL_COST)).rowcount
        print(f"runs 快照列与索引就绪；回填 model_id {models_filled} 行、cost {costs_filled} 行")


if __name__ == "__main__":
    main()
