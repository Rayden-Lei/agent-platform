"""工作流配置快照与线上版本解析（docs/15 FR-075 / WF-02，与 runtime/agent_config.py 同一套语义）。

发布版本是不可变快照，字段只在这里定义一次：发布、回滚上线、恢复到草稿、差异比较、迁移补发都用 snapshot_of，
不再各写一份字段清单（智能体那边 2026-09-25 前发布与回滚各维护一份，漏过字段）。

**运行时一律读线上版本**。工作流的执行入口有五个，只有 test_run_workflow 是例外：
- execute_workflow（界面运行、API Key 运行、人工审核续跑、定时任务共用）
- chat_runner.stream_workflow（工作流对话）
- app/core/scheduler.py（定时任务触发）
  以上经 resolve_live_config 读 published_version 指向的快照；
- test_run_workflow（编辑器内试跑）**读草稿**：它存在的意义就是"改完图先预览效果再决定发不发布"，
  读线上版会让预览所见非所得。这个例外刻意保留，不要为了"统一"把它改成读快照。

workflow_nodes 表是画布位置的展示数据，不参与执行（执行只读 workflows.graph），所以快照里只有 graph；
节点位置改了不影响运行行为，也不必为它产生新版本。
"""
from dataclasses import dataclass

from app.core.exceptions import BizError
from app.db.models import Workflow, WorkflowVersion

# 快照字段：对外行为由这些字段决定。description 也进快照 —— 它出现在列表与对外资料里，
# 与智能体把 description 放进快照同一口径（草稿改名改描述不影响对外展示）。
SNAPSHOT_FIELDS = ("name", "description", "graph")


def snapshot_of(workflow: Workflow) -> dict:
    """当前行（草稿）→ 快照字典。graph 是 JSONB，统一成非空字典，
    比较"草稿与线上是否一致"时不会因 None 与 {} 不同而误判。"""
    return {
        "name": workflow.name,
        "description": workflow.description,
        "graph": workflow.graph or {},
    }


@dataclass(frozen=True)
class WorkflowRunConfig:
    """一次执行用的工作流配置。对外入口是某个发布版本的快照，version 为版本号（运行记录要记下跑的是哪一版）；
    编辑器试跑用的是请求里内联的草稿图，version 为 None。"""

    workflow_id: int
    version: int | None
    name: str
    description: str | None
    graph: dict


def run_config_from_snapshot(workflow_id: int, snapshot: dict, version: int | None = None) -> WorkflowRunConfig:
    """快照（库里的发布版本、草稿的 snapshot_of、迁移回填）→ 执行用配置，来源只有这一条路。"""
    snap = normalize_snapshot(snapshot)
    return WorkflowRunConfig(
        workflow_id=workflow_id, version=version, name=snap["name"] or "",
        description=snap["description"], graph=snap["graph"],
    )


def resolve_live_config(db, workflow_id: int) -> WorkflowRunConfig:
    """当前线上版本的配置。不存在 404；从未发布 403「工作流未发布」（与智能体「智能体未发布」同一口径）。

    工作流没有"下线"状态：要停用一个工作流，停掉它的定时任务、把 API Key 的作用域去掉即可；
    模型与工具那种"下线"概念对工作流没有对应物，不硬造。
    """
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise BizError(404, "工作流不存在")
    if workflow.status != "published" or workflow.published_version is None:
        raise BizError(403, "工作流未发布")
    return load_version_config(db, workflow_id, workflow.published_version)


def load_version_config(db, workflow_id: int, version: int) -> WorkflowRunConfig:
    """指定版本的配置，不再检查发布状态：运行在建运行记录时已按线上版本定好版本号，
    执行时用同一个版本，中途有人发布也不会让"运行记录上的版本号"和"实际执行的图"对不上
    （与 agent_config.load_version_config 同理，resume 续跑依赖这一点）。"""
    wv = db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.version == version).one_or_none()
    if wv is None:
        raise BizError(409, f"工作流的线上版本 v{version} 缺失，请重新发布")
    return run_config_from_snapshot(workflow_id, wv.snapshot, version)


def normalize_snapshot(snapshot: dict | None) -> dict:
    """库里的快照 → 与 snapshot_of 同形的字典。缺的键按"未设置"补齐，比较与恢复都按这个口径。

    这里用 .get() 不是给字段改名留兼容层：迁移脚本把存量工作流回填成 v1 时写的就是 snapshot_of 的形状，
    但历史快照可能来自更早的字段清单，容错是给"读历史数据"用的，新快照一律由 snapshot_of 生成。
    """
    snap = snapshot or {}
    return {
        "name": snap.get("name"),
        "description": snap.get("description"),
        "graph": snap.get("graph") or {},
    }
