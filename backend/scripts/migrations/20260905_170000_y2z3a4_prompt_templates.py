"""迁移：新建 prompt_templates / prompt_template_versions 两张表（Prompt 模板与版本快照）。

改什么：CREATE TABLE IF NOT EXISTS prompt_templates（name 唯一）、prompt_template_versions（template_id + version 唯一）。
为什么：FR-028 Prompt 模板管理（12-差距补齐开发计划 2.7 步）。新表由应用启动的 create_all 自动创建，
  本脚本按 03-数据库设计 第 7 节要求备案，并让"只跑迁移不启动应用"的部署路径也能建表。
影响：只建新表，不动已有数据。
执行后必做：无。
幂等：CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，重复执行无副作用。

执行：cd backend && .venv/bin/python scripts/migrations/20260905_170000_y2z3a4_prompt_templates.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_templates (
                id bigserial PRIMARY KEY,
                name varchar(128) NOT NULL UNIQUE,
                description text,
                content text NOT NULL,
                variables jsonb NOT NULL DEFAULT '[]',
                version integer NOT NULL DEFAULT 1,
                created_by bigint REFERENCES users(id) ON DELETE RESTRICT,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_template_versions (
                id bigserial PRIMARY KEY,
                template_id bigint NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
                version integer NOT NULL,
                content text NOT NULL,
                variables jsonb NOT NULL DEFAULT '[]',
                created_by bigint REFERENCES users(id) ON DELETE SET NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT uq_prompt_template_versions_template_version UNIQUE (template_id, version)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prompt_template_versions_template_id ON prompt_template_versions (template_id)"))
        print("prompt_templates / prompt_template_versions 表就绪")


if __name__ == "__main__":
    main()
