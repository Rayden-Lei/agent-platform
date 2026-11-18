"""迁移（2026-11-18）：tools.name 加唯一约束。

改什么
------
1. 预览：列出 tools 里重名的 name（正常情况下 0 行）。
2. `--apply`：给 tools 加唯一约束 `uq_tools_name`（已存在则跳过）。

为什么
------
工具名是**工作流 tool 节点引用工具的唯一键**（`workflow/engine.py` 按 `Tool.name` 查）。
服务层 `_check_name_taken` 只是给人一句好懂的 409，并发建同名工具时它拦不住；
重名一旦落库，工作流工具节点只能报"工具名称重复"直接失败（2026-11-18 起显式失败，此前是静默取任意一行）。
唯一性必须由数据库兜底（rules/database.md）。

影响
----
- 只加约束，不改任何列、不动数据。
- 存量重名会让 ADD CONSTRAINT 失败：脚本先列出重名清单并以退出码 1 结束，要求人工合并后再执行。
  当前共享库实测 0 个重名，预期直接成功。
- MCP 同步出的工具名带服务器名前缀（`{服务器名}_{远端名}`），已由服务层保证不撞；
  约束是最后一道防线，不是主要手段。

幂等
----
- 约束已存在直接跳过；重复执行第二次 0 行变更。

执行：cd backend && .venv/bin/python scripts/migrations/20261118_100000_t7n3qk_tool_name_unique.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261118_100000_t7n3qk_tool_name_unique.py --apply    # 执行
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

CONSTRAINT = "uq_tools_name"
DUPLICATES = "SELECT name, count(*) AS n, array_agg(id ORDER BY id) AS ids FROM tools GROUP BY name HAVING count(*) > 1 ORDER BY name"
ADD_CONSTRAINT = f"ALTER TABLE tools ADD CONSTRAINT {CONSTRAINT} UNIQUE (name)"


def _constraint_exists(conn) -> bool:
    return conn.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
        {"n": CONSTRAINT},
    ).first() is not None


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        if _constraint_exists(conn):
            print(f"约束 {CONSTRAINT} 已存在，无需执行")
            return
        duplicates = conn.execute(text(DUPLICATES)).all()
        if duplicates:
            print("tools 存在重名，先人工合并再执行（重名会让工作流工具节点无法确定调哪一个）：")
            for row in duplicates:
                print(f"  {row[0]!r} 出现 {row[1]} 次，id={list(row[2])}")
            sys.exit(1)
        total = conn.execute(text("SELECT count(*) FROM tools")).scalar()
        print(f"tools 共 {total} 行，无重名")
        if not apply:
            print(f"预览：将执行 {ADD_CONSTRAINT}；确认后加 --apply 执行")
            return
        conn.execute(text(ADD_CONSTRAINT))
        print(f"已执行：{ADD_CONSTRAINT}")


if __name__ == "__main__":
    main()
