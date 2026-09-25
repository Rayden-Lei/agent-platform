"""智能体配置快照（docs/15 3.2，FR-039）。

发布版本是不可变快照，字段只在这里定义一次：发布、回滚上线、恢复到草稿、差异比较、迁移补发都用 snapshot_of，
不再各写一份字段清单（2026-09-25 前发布与回滚各维护一份，容易漏字段）。
"""
from app.db.models import Agent

# 快照字段：对外行为由这些字段决定。workflow_id 是预留字段（对话不使用），照旧随快照保存，恢复时原样还原
SNAPSHOT_FIELDS = (
    "name", "description", "system_prompt", "model_id", "params", "kb_ids", "tool_ids", "workflow_id",
    "prompt_template_id", "prompt_template_version", "prompt_variables",
)


def snapshot_of(agent: Agent) -> dict:
    """当前行（草稿）→ 快照字典。JSON 字段统一成非空的空值，比较"草稿与线上是否一致"时不会因 None 与 {} 不同而误判。"""
    return {
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "model_id": agent.model_id,
        "params": agent.params or {},
        "kb_ids": list(agent.kb_ids or []),
        "tool_ids": list(agent.tool_ids or []),
        "workflow_id": agent.workflow_id,
        "prompt_template_id": agent.prompt_template_id,
        "prompt_template_version": agent.prompt_template_version,
        "prompt_variables": agent.prompt_variables or {},
    }


def normalize_snapshot(snapshot: dict | None) -> dict:
    """库里的快照 → 与 snapshot_of 同形的字典。早期快照没有模板三字段，缺的键按"未设置"补齐，比较与恢复都按这个口径。"""
    snap = snapshot or {}
    return {
        "name": snap.get("name"),
        "description": snap.get("description"),
        "system_prompt": snap.get("system_prompt"),
        "model_id": snap.get("model_id"),
        "params": snap.get("params") or {},
        "kb_ids": list(snap.get("kb_ids") or []),
        "tool_ids": list(snap.get("tool_ids") or []),
        "workflow_id": snap.get("workflow_id"),
        "prompt_template_id": snap.get("prompt_template_id"),
        "prompt_template_version": snap.get("prompt_template_version"),
        "prompt_variables": snap.get("prompt_variables") or {},
    }
