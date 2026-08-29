"""迁移：为所有外键补充 ondelete 语义。

改什么：重建 23 个外键约束，补上 ON DELETE 规则。
为什么：models.py 此前所有 ForeignKey 均未指定 ondelete，PostgreSQL 落为 NO ACTION，
  删除被引用的父记录时靠应用层手动级联，易产生孤儿数据；现按 docs/03 规范补全：
  - 配置类之间的引用（created_by、agents.model_id/workflow_id）→ RESTRICT
  - 运行类数据（conversations/messages/runs/run_nodes/documents/document_chunks/
    agent_versions/api_keys/scheduled_jobs）→ CASCADE
  - 审计日志 audit_logs.user_id → SET NULL（保留审计记录）

影响：重建约束本身不删数据；行为变化——
  - 删除被智能体引用的模型/工作流、或删除仍有配置资源的用户，现在会被 RESTRICT 阻止。
  - 删除智能体/工作流/知识库/用户时，其运行数据由数据库自动级联删除。
执行后必做：无（无需清缓存）；应用层 service 已配合做前置校验。

幂等：DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT，重复执行结果一致。

执行：cd backend && .venv/bin/python3 scripts/migrations/20250829_153100_d4e5f6_foreign_key_ondelete.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

# (约束名, 表, 列, 引用表, ondelete)
FKS = [
    ("models_created_by_fkey", "models", "created_by", "users", "RESTRICT"),
    ("agents_model_id_fkey", "agents", "model_id", "models", "RESTRICT"),
    ("agents_workflow_id_fkey", "agents", "workflow_id", "workflows", "RESTRICT"),
    ("agents_created_by_fkey", "agents", "created_by", "users", "RESTRICT"),
    ("knowledge_bases_created_by_fkey", "knowledge_bases", "created_by", "users", "RESTRICT"),
    ("workflows_created_by_fkey", "workflows", "created_by", "users", "RESTRICT"),
    ("agent_versions_agent_id_fkey", "agent_versions", "agent_id", "agents", "CASCADE"),
    ("documents_kb_id_fkey", "documents", "kb_id", "knowledge_bases", "CASCADE"),
    ("document_chunks_doc_id_fkey", "document_chunks", "doc_id", "documents", "CASCADE"),
    ("document_chunks_kb_id_fkey", "document_chunks", "kb_id", "knowledge_bases", "CASCADE"),
    ("workflow_nodes_workflow_id_fkey", "workflow_nodes", "workflow_id", "workflows", "CASCADE"),
    ("conversations_agent_id_fkey", "conversations", "agent_id", "agents", "CASCADE"),
    ("conversations_workflow_id_fkey", "conversations", "workflow_id", "workflows", "CASCADE"),
    ("conversations_user_id_fkey", "conversations", "user_id", "users", "CASCADE"),
    ("messages_conversation_id_fkey", "messages", "conversation_id", "conversations", "CASCADE"),
    ("runs_agent_id_fkey", "runs", "agent_id", "agents", "CASCADE"),
    ("runs_workflow_id_fkey", "runs", "workflow_id", "workflows", "CASCADE"),
    ("runs_user_id_fkey", "runs", "user_id", "users", "CASCADE"),
    ("run_nodes_run_id_fkey", "run_nodes", "run_id", "runs", "CASCADE"),
    ("scheduled_jobs_workflow_id_fkey", "scheduled_jobs", "workflow_id", "workflows", "CASCADE"),
    ("scheduled_jobs_user_id_fkey", "scheduled_jobs", "user_id", "users", "CASCADE"),
    ("api_keys_user_id_fkey", "api_keys", "user_id", "users", "CASCADE"),
    ("audit_logs_user_id_fkey", "audit_logs", "user_id", "users", "SET NULL"),
]


def main() -> None:
    with engine.begin() as conn:
        for name, tbl, col, reftbl, ondelete in FKS:
            conn.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT IF EXISTS "{name}"'))
            conn.execute(text(
                f'ALTER TABLE "{tbl}" ADD CONSTRAINT "{name}" '
                f'FOREIGN KEY ({col}) REFERENCES "{reftbl}"(id) ON DELETE {ondelete}'
            ))
            print(f"{tbl}.{col} -> {reftbl}.id  ON DELETE {ondelete}")
    print("外键 ondelete 迁移完成。")


if __name__ == "__main__":
    main()
