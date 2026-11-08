"""迁移（2026-11-08）：新建 llm_calls 表 —— 模型调用全量日志。

改什么：
  CREATE TABLE IF NOT EXISTS llm_calls：每次模型调用一行
  CREATE INDEX ix_llm_calls_run_id_id：按运行看调用链（run_id, id）
  CREATE INDEX ix_llm_calls_started_at：按时间排查
  CREATE INDEX ix_llm_calls_model_id / ix_llm_calls_purpose：按模型、按用途聚合

为什么：原来的调用链（run_nodes 的 trace step）只记 content_chars 与工具名 ——
排查"模型为什么这么回答""为什么没调工具""上游到底返回了什么"时全都看不到。
而这些问题只能靠原始报文回答。新表存请求地址（完整 URL）、请求体（messages 全文 +
工具定义 + 参数）、响应原文（含 SSE 帧）、解析出的正文与思考过程、工具调用、用量、耗时、错误原文。

打码口径：**只有凭据打码**（api_key / Authorization 换成 ***），地址、请求体、
响应体、错误原文全部原样保留 —— 凭据不进日志是硬约束，其余对使用者完全透明。
单条报文按 LLM_LOG_MAX_CHARS（默认 256KB）截断，超出时注明原文长度。

为什么 run_id / model_id 不设外键：运行记录会被清理，而调用日志是排查依据，要能独立留存；
两者只作为可查询的普通列（外键的 CASCADE 会把排查依据跟着删掉）。

影响：只建新表，不改任何存量表与列。不记录时（LLM_LOG_ENABLED=false）不写任何行，
业务行为完全不变（采集层失败只记 WARNING，绝不影响对话）。

执行：cd backend && .venv/bin/python scripts/migrations/20261108_110000_llm_calls.py

幂等：CREATE TABLE / CREATE INDEX 全部 IF NOT EXISTS，重复执行无副作用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine

DDL = [
    """
    CREATE TABLE IF NOT EXISTS llm_calls (
        id bigserial PRIMARY KEY,
        run_id bigint,
        model_id bigint,
        model_name varchar(128) NOT NULL DEFAULT '',
        purpose varchar(24) NOT NULL DEFAULT 'chat',
        url varchar(512) NOT NULL DEFAULT '',
        method varchar(8) NOT NULL DEFAULT 'POST',
        request_body jsonb,
        response_body text,
        response_text text,
        reasoning_text text,
        tools_offered jsonb NOT NULL DEFAULT '[]',
        tool_calls jsonb NOT NULL DEFAULT '[]',
        status varchar(16) NOT NULL DEFAULT 'success',
        http_status integer,
        error text,
        prompt_tokens integer NOT NULL DEFAULT 0,
        completion_tokens integer NOT NULL DEFAULT 0,
        first_token_ms integer,
        duration_ms integer NOT NULL DEFAULT 0,
        started_at timestamptz NOT NULL DEFAULT now(),
        truncated boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # 索引全部由 ORM 模型（LlmCall.__table_args__ / index=True）声明，create_all 会建。
    # 这里**不再重复建模已声明的索引**：create_all 与迁移在同一进程里先后执行时，
    # 两边建同名索引会 DuplicateTable 中断建表，连锁导致后续所有表都不存在
    # （2026-11-08 空库 CI 连红四次）。只在"只跑迁移不启动应用"的部署路径里，
    # 表本身由下面的 CREATE TABLE 建出来，索引随后由应用启动时的 create_all 补齐。
]


def main() -> None:
    with engine.begin() as conn:
        for statement in DDL:
            conn.execute(text(statement))
    print(f"llm_calls 就绪（执行 {len(DDL)} 条 DDL）")


if __name__ == "__main__":
    main()
