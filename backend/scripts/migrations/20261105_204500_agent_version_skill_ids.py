"""迁移（docs/17 §4.3，P2 技能，2026-11-05）：agent_versions.snapshot 补 skill_ids。

改什么：给所有 agent_versions 行的 snapshot 补上 "skill_ids": []（已有 skill_ids 的行不动）。

为什么：技能绑定进快照（runtime/agent_config.SNAPSHOT_FIELDS 加 skill_ids）。发布、回滚、
恢复到草稿、草稿与线上的差异比较都按同一份字段清单走，存量快照缺这个键会让
"草稿 skill_ids=[] 与线上快照缺键"被 normalize_snapshot 补成同一个值而不报错，
但快照本身不完整 —— 契约一次切换不留运行时兜底，存量数据靠本脚本补齐。

影响：只加一个键，值恒为空数组（存量智能体从未绑定过技能）。
skill_ids 里存的是 ID，不含技能正文：改技能对所有线上智能体立刻生效（与知识库文档同口径），
不随快照固化。

执行：cd backend && .venv/bin/python scripts/migrations/20261105_204500_agent_version_skill_ids.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261105_204500_agent_version_skill_ids.py --apply    # 执行

幂等：只更新 snapshot 里还没有 skill_ids 键的行，重复执行第二次影响 0 行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

COUNT_MISSING = "SELECT count(*) FROM agent_versions WHERE NOT (snapshot ? 'skill_ids')"
COUNT_ALL = "SELECT count(*) FROM agent_versions"
SAMPLE = "SELECT agent_id, version FROM agent_versions WHERE NOT (snapshot ? 'skill_ids') ORDER BY id LIMIT 10"
BACKFILL = "UPDATE agent_versions SET snapshot = snapshot || '{\"skill_ids\": []}'::jsonb WHERE NOT (snapshot ? 'skill_ids')"


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        total = conn.execute(text(COUNT_ALL)).scalar()
        missing = conn.execute(text(COUNT_MISSING)).scalar()
        print(f"agent_versions：{total} 行，其中缺 skill_ids 的 {missing} 行")
        if missing:
            rows = conn.execute(text(SAMPLE)).all()
            print("待补样本（agent_id, version）：", [tuple(r) for r in rows])
        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return
        result = conn.execute(text(BACKFILL))
        print(f"已执行：补齐 {result.rowcount} 行快照的 skill_ids")


if __name__ == "__main__":
    main()
