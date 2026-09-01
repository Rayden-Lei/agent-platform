"""迁移：knowledge_bases 增加权限字段（is_public / visible_roles / policy_version）。

RBAC 权限加固第一阶段：知识库级可见性。
- is_public=True：所有角色可见（默认，兼容存量数据）
- is_public=False：仅 visible_roles 内角色可见
- policy_version：权限变更时 +1，用于缓存失效

幂等：使用 IF NOT EXISTS / IF NOT EXISTS。
执行：cd backend && python3 scripts/migrations/20260901_000100_kb_permission_fields.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT true"))
        conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS visible_roles jsonb NOT NULL DEFAULT '[]'"))
        conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS policy_version integer NOT NULL DEFAULT 1"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_knowledge_bases_is_public ON knowledge_bases (is_public)"))
        print("knowledge_bases 权限字段迁移完成")


if __name__ == "__main__":
    main()
