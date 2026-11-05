"""存量工作流图的输入声明回填（docs/15 WF-04 / M3，2026-11-05）。

运行入参一次切换到 {inputs: {...}}（D-32），开始节点必须声明变量才有地方接。
存量图的开始节点没有 config.variables，这里按"原来唯一的入参叫 input"补上一条，
之后 {{input}} / {{start.input}} 都指向它，行为与切换前一致。

幂等：已经有 variables 声明的开始节点不动（哪怕声明的不是 input）；重复执行无副作用。
结束节点不补：没声明 outputs 时结束节点保持"上游输出即结果"的原行为，补了反而会改变输出形状。
"""
import json
import logging
import os
import sys

# 与其它迁移脚本一致：允许从 backend 目录直接执行（scripts/migrations/xxx.py）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.db.models import Workflow
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _patch_start_nodes(graph: dict) -> tuple[dict, int]:
    """给没有声明变量的开始节点补 {name: input, type: text}，返回 (新图, 补了几个)。"""
    patched = 0
    for node in (graph or {}).get("nodes") or []:
        if node.get("type") != "start":
            continue
        config = node.get("config") or {}
        if config.get("variables"):
            continue
        node["config"] = {**config, "variables": [{"name": "input", "type": "text", "description": "运行输入"}]}
        patched += 1
    return graph, patched


def upgrade() -> None:
    db = SessionLocal()
    try:
        rows = db.query(Workflow).all()
        touched = 0
        for w in rows:
            graph, patched = _patch_start_nodes(w.graph or {})
            if patched:
                w.graph = graph
                touched += 1
                logger.info("工作流 %s（%s）补了 %d 个开始节点变量声明", w.id, w.name, patched)
        db.commit()
        print(f"回填完成：{touched} / {len(rows)} 张工作流有变更")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    upgrade()
