"""迁移：agents 增加 Prompt 模板绑定字段 prompt_template_id / prompt_template_version / prompt_variables。

改什么：ALTER TABLE agents ADD COLUMN prompt_template_id bigint REFERENCES prompt_templates(id) ON DELETE SET NULL；
        ADD COLUMN prompt_template_version integer；ADD COLUMN prompt_variables jsonb NOT NULL DEFAULT '{}'。
为什么：FR-028 智能体绑定模板（12-差距补齐开发计划 2.8 步）。models.py 已加列，create_all 不会给已存在的表补列。
  依赖 prompt_templates 表已存在（20260905_170000_y2z3a4 或应用启动建表）。
影响：只加列，存量智能体三个字段为空 / {}，行为不变（仍读 system_prompt）。
执行后必做：无。
幂等：ADD COLUMN IF NOT EXISTS（列已存在时整条子句连同外键约束一起跳过），重复执行无副作用。

执行：cd backend && .venv/bin/python scripts/migrations/20260905_180000_b5c6d7_agents_prompt_template_fields.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS prompt_template_id bigint REFERENCES prompt_templates(id) ON DELETE SET NULL"))
        conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS prompt_template_version integer"))
        conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS prompt_variables jsonb NOT NULL DEFAULT '{}'"))
        print("agents.prompt_template_id / prompt_template_version / prompt_variables 列就绪")


if __name__ == "__main__":
    main()
