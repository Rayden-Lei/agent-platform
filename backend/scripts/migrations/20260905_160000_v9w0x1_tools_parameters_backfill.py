"""迁移：给存量 HTTP 工具回填空的参数声明 config.parameters。

改什么：tools 表中 type='http' 且 config 没有 parameters 键的行，config 合并
        {"parameters": {"type": "object", "properties": {}, "required": []}}。
为什么：FR-030（12-差距补齐开发计划 2.3 步）。后端上线后未声明参数的 HTTP 工具已按无参数工具暴露给模型，
  本脚本只把这个隐式状态显式化，并打印受影响清单供通知使用方逐个补声明；不改变运行时行为，
  漏跑只影响工具页"未声明参数"标签的数据来源。
影响：只补 JSON 键，其他字段不动；逐行打印 id / name。
执行后必做：把清单发给这些工具的使用方，在工具页补参数声明。
幂等：已有 parameters 的行不满足条件，重复执行为 0 行。

执行：cd backend && .venv/bin/python scripts/migrations/20260905_160000_v9w0x1_tools_parameters_backfill.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

EMPTY_PARAMETERS = '{"parameters": {"type": "object", "properties": {}, "required": []}}'
# config 理论上非空，COALESCE 只是防御历史脏数据；jsonb_exists 即 ? 运算符，避免驱动把 ? 误当占位符
MISSING = "type = 'http' AND NOT jsonb_exists(COALESCE(config, '{}'::jsonb), 'parameters')"


def backfill(conn) -> list[tuple[int, str]]:
    """回填并返回受影响的 (id, name) 清单；无事可做返回空列表。"""
    rows = conn.execute(text(f"SELECT id, name FROM tools WHERE {MISSING} ORDER BY id")).fetchall()
    if rows:
        conn.execute(
            text(f"UPDATE tools SET config = COALESCE(config, '{{}}'::jsonb) || CAST(:empty AS jsonb) WHERE {MISSING}"),
            {"empty": EMPTY_PARAMETERS},
        )
    return [(r[0], r[1]) for r in rows]


def main() -> None:
    with engine.begin() as conn:
        affected = backfill(conn)
    if not affected:
        print("没有缺少参数声明的 HTTP 工具，无需回填。")
        return
    print(f"已为 {len(affected)} 个 HTTP 工具回填空参数声明，请通知使用方补声明：")
    for tool_id, name in affected:
        print(f"  id={tool_id} name={name}")


if __name__ == "__main__":
    main()
