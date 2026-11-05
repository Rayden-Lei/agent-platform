"""智能体配置快照与线上配置解析（docs/15 3.2，FR-039）。

发布版本是不可变快照，字段只在这里定义一次：发布、回滚上线、恢复到草稿、差异比较、迁移补发都用 snapshot_of，
不再各写一份字段清单（2026-09-25 前发布与回滚各维护一份，容易漏字段）。
对外入口（登录对话、API Key、工作流智能体节点、可对话列表）一律经 resolve_live_config 读线上快照，不读草稿行。
"""
from dataclasses import dataclass

from app.core.exceptions import BizError
from app.db.models import Agent, AgentVersion, ModelConfig

# 快照字段：对外行为由这些字段决定。workflow_id 是预留字段（对话不使用），照旧随快照保存，恢复时原样还原
SNAPSHOT_FIELDS = (
    "name", "description", "system_prompt", "model_id", "params", "kb_ids", "tool_ids", "skill_ids", "workflow_id",
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
        "skill_ids": list(agent.skill_ids or []),
        "workflow_id": agent.workflow_id,
        "prompt_template_id": agent.prompt_template_id,
        "prompt_template_version": agent.prompt_template_version,
        "prompt_variables": agent.prompt_variables or {},
    }


@dataclass(frozen=True)
class AgentRunConfig:
    """一次回答用的智能体配置。对外入口是某个发布版本的快照，version 为版本号（运行记录要记下回答用的是哪一版）；
    装配页调试用的是编辑器里的内容或已保存的草稿，version 为 None。"""

    agent_id: int
    version: int | None
    name: str
    description: str | None
    system_prompt: str
    model_id: int
    params: dict
    kb_ids: list
    tool_ids: list
    # 技能白名单（docs/17 §4）：只在这里面的技能能进「可用技能」目录，load_skill 也只认它们。
    # 技能正文不随快照固化 —— 改技能立刻对所有线上智能体生效（与知识库文档同口径），
    # 快照里只有 ID，装配时现查 skills 表。
    skill_ids: list


def run_config_from_snapshot(agent_id: int, snapshot: dict, version: int | None = None) -> AgentRunConfig:
    """快照（库里的发布版本、草稿的 snapshot_of、调试请求里的内联配置）→ 回答用的配置，三种来源只走这一条路。"""
    snap = normalize_snapshot(snapshot)
    return AgentRunConfig(
        agent_id=agent_id, version=version, name=snap["name"], description=snap["description"], system_prompt=snap["system_prompt"] or "",
        model_id=snap["model_id"], params=snap["params"], kb_ids=snap["kb_ids"], tool_ids=snap["tool_ids"],
        skill_ids=snap["skill_ids"],
    )


def resolve_live_config(db, agent_id: int) -> AgentRunConfig:
    """当前线上版本的配置。不存在 404；已下线 403「智能体已下线」；从未发布 403「智能体未发布」。"""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise BizError(404, "智能体不存在")
    if agent.status == "offline":
        raise BizError(403, "智能体已下线")
    if agent.status != "published" or agent.published_version is None:
        raise BizError(403, "智能体未发布")
    return load_version_config(db, agent_id, agent.published_version)


def load_version_config(db, agent_id: int, version: int) -> AgentRunConfig:
    """指定版本的配置，不再检查上下线：对话在建运行记录时已按线上版本定好版本号，构建上下文用同一个版本，
    中途有人发布也不会让"运行记录上的版本"和"实际回答用的配置"对不上。"""
    av = db.query(AgentVersion).filter(AgentVersion.agent_id == agent_id, AgentVersion.version == version).one_or_none()
    if av is None:
        raise BizError(409, f"智能体的线上版本 v{version} 缺失，请重新发布")
    return run_config_from_snapshot(agent_id, av.snapshot, version)


def usable_model(db, model_id: int) -> ModelConfig:
    """回答要用的模型：不存在或已停用 400「模型不可用」。对话与工作流智能体节点共用（此前节点不查停用，停用对工作流不起作用）。"""
    model = db.get(ModelConfig, model_id)
    if model is None or not model.is_enabled:
        raise BizError(400, "模型不可用")
    return model


def normalize_snapshot(snapshot: dict | None) -> dict:
    """库里的快照 → 与 snapshot_of 同形的字典。缺的键按"未设置"补齐，比较与恢复都按这个口径。

    这里用 .get() 不是给字段改名留兼容层：normalize 面对的三类来源里，"装配页调试的内联配置"
    由前端构造、允许不完整（docs/15 3.4），必须能容忍缺键。库里的存量快照由迁移脚本补齐，
    新快照一律由 snapshot_of 生成，键齐全。
    """
    snap = snapshot or {}
    return {
        "name": snap.get("name"),
        "description": snap.get("description"),
        "system_prompt": snap.get("system_prompt"),
        "model_id": snap.get("model_id"),
        "params": snap.get("params") or {},
        "kb_ids": list(snap.get("kb_ids") or []),
        "tool_ids": list(snap.get("tool_ids") or []),
        "skill_ids": list(snap.get("skill_ids") or []),
        "workflow_id": snap.get("workflow_id"),
        "prompt_template_id": snap.get("prompt_template_id"),
        "prompt_template_version": snap.get("prompt_template_version"),
        "prompt_variables": snap.get("prompt_variables") or {},
    }
