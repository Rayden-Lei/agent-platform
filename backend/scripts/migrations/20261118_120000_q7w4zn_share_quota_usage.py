"""迁移（2026-11-18）：新增 share_quota_usage 表，分享链接每日额度改为数据库原子扣减。

改什么
------
1. 预览：检查 share_quota_usage 表是否已存在；存在则什么都不做。
2. `--apply`：CREATE TABLE IF NOT EXISTS share_quota_usage + 唯一约束 + 索引。

为什么
------
`share_service.check_chat_quota` 原来是"先 count(runs) 再放行"的 check-then-act：
并发请求各自 count 到同一个未超限的数字后全部放行，**链接每日总量这个成本硬上限直接失效**。
改成数据库层的原子扣减（照 `api_key_service.authenticate` 的既有范式：
`UPDATE ... WHERE used < 上限` 按影响行数判断），并发由行锁串行化，不会超扣。
原子扣减需要一个可按 (分享, 自然日, 访客) 定位并累加的计数行，因此新建这张表。

按 (share_id, usage_date, visitor_id) 唯一：
- usage_date 存业务时区（REPORT_TIMEZONE）的自然日，与运营统计同一口径；
- visitor_id 空串表示"整条链接的总量"，非空是单个访客的量。
  用空串而不是 NULL —— PostgreSQL 唯一约束视 NULL 互不相等，用 NULL 时"整条链接"那行
  每次都能再插一条，唯一约束形同虚设。

影响
----
- 只新增表，不改任何现有列、不动现有数据。
- 上线后第一天的额度从 0 开始：迁移不回填历史 runs 的计数。
  理由：回填需要按天 + 按访客聚合 runs/messages，成本高且语义已变（旧口径按 runs 条数，
  新口径按"放行的对话次数"）；跨过部署当天就自然对齐。
- 表随分享删除级联（ON DELETE CASCADE），删分享不留孤儿计数行。

执行后必做
----------
1. 确认 `SELECT count(*) FROM share_quota_usage` 可执行。
2. 重启后端（代码与表要同时到位；模型声明已在 app/db/models.py 的 ShareQuotaUsage）。

幂等
----
- CREATE TABLE / CREATE INDEX 均带 IF NOT EXISTS，唯一约束用 DO 块先查 pg_constraint 再建；
  重复执行第二次 0 行变更。

执行：cd backend && .venv/bin/python scripts/migrations/20261118_120000_q7w4zn_share_quota_usage.py            # 预览
      cd backend && .venv/bin/python scripts/migrations/20261118_120000_q7w4zn_share_quota_usage.py --apply    # 执行
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

TABLE = "share_quota_usage"
CONSTRAINT = "uq_share_quota_usage_share_day_visitor"

CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id BIGSERIAL PRIMARY KEY,
    share_id BIGINT NOT NULL REFERENCES agent_shares(id) ON DELETE CASCADE,
    usage_date TIMESTAMPTZ NOT NULL,
    visitor_id VARCHAR(64) NOT NULL DEFAULT '',
    used INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
CREATE_INDEX = f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_share_id ON {TABLE} (share_id)"
ADD_CONSTRAINT = f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} UNIQUE (share_id, usage_date, visitor_id)"


def _table_exists(conn) -> bool:
    return conn.execute(text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is not None


def _constraint_exists(conn) -> bool:
    return conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": CONSTRAINT}).first() is not None


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))
        exists = _table_exists(conn)
        has_constraint = exists and _constraint_exists(conn)
        if exists and has_constraint:
            rows = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar()
            print(f"表 {TABLE} 与唯一约束均已存在（当前 {rows} 行），无需执行")
            return
        print(f"表 {TABLE} 已存在：{exists}；唯一约束已存在：{has_constraint}")
        if not apply:
            print(f"预览：将执行\n  {CREATE_TABLE.strip()}\n  {CREATE_INDEX}\n  {ADD_CONSTRAINT}")
            print("确认后加 --apply 执行")
            return
        conn.execute(text(CREATE_TABLE))
        conn.execute(text(CREATE_INDEX))
        if not has_constraint:
            conn.execute(text(ADD_CONSTRAINT))
        print(f"已执行：建表 {TABLE}、索引 ix_{TABLE}_share_id、唯一约束 {CONSTRAINT}")


if __name__ == "__main__":
    main()
