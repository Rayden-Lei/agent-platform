"""迁移（docs/17 §4.3，P2 技能，2026-11-05）：新建 skills 表，agents 加 skill_ids。

改什么：
  CREATE TABLE IF NOT EXISTS skills：技能（操作手册）本体，name 唯一，正文上限由接口把关
  CREATE INDEX IF NOT EXISTS ix_skills_is_enabled：技能页按"启用中"过滤
  ALTER TABLE agents ADD COLUMN IF NOT EXISTS skill_ids jsonb NOT NULL DEFAULT '[]'：智能体绑定的技能

为什么：技能与提示词模板分工不同（docs/17 §4.1）——模板是"人设"，保存时渲染进 system_prompt；
技能是"操作手册"，运行时按需加载。此前没有承载技能的载体。
绑定沿用 kb_ids / tool_ids 的 JSONB 数组风格（本项目已有两处先例），代价是没有外键，
技能删除后残留 ID 在装配时忽略，与现状同级。

影响：只建新表 + 加一个带默认值的列，存量智能体 skill_ids 为空数组，行为不变（不装配任何技能）。
新表由应用启动的 create_all 也会自动建，本脚本让"只跑迁移不启动应用"的部署路径也能建表。

执行：cd backend && .venv/bin/python scripts/migrations/20261105_203000_skill_table.py

幂等：CREATE TABLE / CREATE INDEX / ADD COLUMN 全部 IF NOT EXISTS，重复执行无副作用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    """
    CREATE TABLE IF NOT EXISTS skills (
        id bigserial PRIMARY KEY,
        name varchar(64) NOT NULL UNIQUE,
        display_name varchar(128) NOT NULL,
        description text NOT NULL,
        content text NOT NULL,
        resources jsonb NOT NULL DEFAULT '[]',
        always_on boolean NOT NULL DEFAULT false,
        is_enabled boolean NOT NULL DEFAULT true,
        version integer NOT NULL DEFAULT 1,
        created_by bigint REFERENCES users(id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_skills_is_enabled ON skills (is_enabled)",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS skill_ids jsonb NOT NULL DEFAULT '[]'",
]


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        has_skills = conn.execute(text(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'skills'")).scalar()
        has_skill_ids = conn.execute(text(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'agents' AND column_name = 'skill_ids'")).scalar()
        agents_total = conn.execute(text("SELECT count(*) FROM agents")).scalar()
        print(f"skills 表{'已存在' if has_skills else '待新建'}；agents.skill_ids 列{'已存在' if has_skill_ids else '待新增'}；现有智能体 {agents_total} 个（回填为空数组）")
        for statement in DDL:
            conn.execute(text(statement))
        print("已执行：skills 表 / 启用索引 / agents.skill_ids 就绪")


if __name__ == "__main__":
    main()
