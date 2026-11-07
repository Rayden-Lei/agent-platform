"""迁移（2026-11-08）：把「知识库的向量模型」从一个没生效的自由字符串改成真正的外键。

改什么
------
1. 新建 embedding_models 表（向量模型配置：地址、密钥密文、模型名、维度、单请求条数、启用状态）。
2. knowledge_bases 加 embedding_model_id（非空外键，RESTRICT），删掉 embedding_model 自由字符串列。
3. 播种：用当前 .env 的 EMBEDDING_* 建一行向量模型（如果表里还没有），并把所有存量知识库绑到它上面。

为什么
------
改造前 knowledge_bases.embedding_model 只是记录，实际向量化固定读全局 settings.EMBEDDING_MODEL；
默认值还写成了本平台根本不存在的 text-embedding-3-small。建完库看到的模型名和实际用的模型是两回事，
排查"检索不准"时会被这个字段直接带偏（docs/03 第 129 行自己写了"仅记录用"）。

改造后建库必须选一个真实存在且启用的模型，入库与检索都按它走（docs/09"向量模型按知识库配置"）。

影响
----
- 结构：新增 1 张表、knowledge_bases 换 1 列。
- 数据：存量知识库全部绑到播种出来的那一行（等价于它们现在实际在用的全局模型），不丢数据。
- 存量切片不用动：它们的向量本来就是全局模型产的，绑定关系与之一致；切片 meta 里的
  embedding_model 快照保持原样（那是"这批切片实际是什么模型产的"，属于审计信息）。
- 执行后：后端需重启（ORM 与路由变了）。

注意：维度必须与 document_chunks.embedding 的列宽一致（当前 1024）。
播种行的 dim 取 document_chunks.embedding 的实际列宽，而不是 .env 的 EMBEDDING_DIM ——
二者不一致时以库为准，否则播种出来的模型一入库就会因维度不符报错。

执行
----
    cd backend && .venv/bin/python scripts/migrations/20261108_010000_w8k2mn_embedding_models.py            # 预览
    cd backend && .venv/bin/python scripts/migrations/20261108_010000_w8k2mn_embedding_models.py --apply    # 执行

幂等：建表用 IF NOT EXISTS；加列前先查 information_schema；播种按 name 判重；
绑定只更新 embedding_model_id IS NULL 的行。重复执行第二次影响 0 行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.config import settings
from app.core.security import encrypt_secret
from app.db.session import engine

SEED_NAME = "全局向量模型（.env）"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS embedding_models (
    id            BIGSERIAL PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,
    provider      VARCHAR(32)  NOT NULL,
    api_base      VARCHAR(255) NOT NULL,
    api_key_enc   TEXT         NOT NULL,
    model_name    VARCHAR(128) NOT NULL,
    dim           INTEGER      NOT NULL,
    request_size  INTEGER      NOT NULL DEFAULT 20,
    is_enabled    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by    BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
)
"""
CREATE_INDEX = "CREATE INDEX IF NOT EXISTS ix_embedding_models_provider ON embedding_models (provider)"

HAS_COL = """
SELECT count(*) FROM information_schema.columns
WHERE table_name = 'knowledge_bases' AND column_name = 'embedding_model_id'
"""
HAS_OLD_COL = """
SELECT count(*) FROM information_schema.columns
WHERE table_name = 'knowledge_bases' AND column_name = 'embedding_model'
"""
ADD_COL = "ALTER TABLE knowledge_bases ADD COLUMN embedding_model_id BIGINT REFERENCES embedding_models(id) ON DELETE RESTRICT"
DROP_OLD_COL = "ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS embedding_model"
COUNT_SEED = "SELECT count(*) FROM embedding_models WHERE name = :name"
COUNT_UNBOUND = "SELECT count(*) FROM knowledge_bases WHERE embedding_model_id IS NULL"


def _chunk_dim(conn) -> int:
    """document_chunks.embedding 的实际列宽。以库为准：维度必须与定长列一致，否则写入必失败。"""
    row = conn.execute(text("""
        SELECT atttypmod FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'document_chunks' AND a.attname = 'embedding'
    """)).scalar()
    # pgvector 把维度存在 atttypmod 里，原样返回就是维度
    return int(row) if row else settings.EMBEDDING_DIM


def main() -> None:
    apply = "--apply" in sys.argv
    with engine.begin() as conn:
        conn.execute(text("SET lock_timeout = '5s'"))

        dim = _chunk_dim(conn)
        has_table = conn.execute(text("SELECT to_regclass('public.embedding_models') IS NOT NULL")).scalar()
        has_col = conn.execute(text(HAS_COL)).scalar()
        has_old = conn.execute(text(HAS_OLD_COL)).scalar()
        # 表还不存在时不能查它（预览就报 UndefinedTable），先看 to_regclass
        seed_rows = conn.execute(text(COUNT_SEED), {"name": SEED_NAME}).scalar() if has_table else 0
        unbound = conn.execute(text(COUNT_UNBOUND)).scalar() if has_col else None
        old_values = None
        if has_old:
            old_values = [r[0] for r in conn.execute(text(
                "SELECT DISTINCT embedding_model FROM knowledge_bases WHERE embedding_model IS NOT NULL"
            )).all()]

        print(f"切片表向量列宽：{dim}（.env 的 EMBEDDING_DIM={settings.EMBEDDING_DIM}）")
        print(f"embedding_models 表：{'已存在' if has_table else '待建'}")
        print(f"knowledge_bases.embedding_model_id：{'已存在' if has_col else '待加'}")
        print(f"knowledge_bases.embedding_model（旧列）：{'存在，待删' if has_old else '已删'}")
        if old_values:
            print(f"旧列里出现过的取值（将被丢弃）：{old_values}")
        if has_col:
            print(f"未绑定向量模型的知识库：{unbound} 个")
        print(f"播种行「{SEED_NAME}」：{'已存在' if seed_rows else '待建'}")

        if not apply:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return

        conn.execute(text(CREATE_TABLE))
        conn.execute(text(CREATE_INDEX))
        print("已建表 embedding_models")

        if not conn.execute(text(COUNT_SEED), {"name": SEED_NAME}).scalar():
            if not settings.EMBEDDING_API_KEY:
                # 没配密钥时播种空密钥行会让建库"看起来能用"但入库全走 hash，比没有模型更误导
                raise SystemExit(
                    "中止：.env 里没有 EMBEDDING_API_KEY，无法播种向量模型。"
                    "请先配置好向量服务，或执行完后在「向量模型」页面手动新建一个。"
                )
            conn.execute(text("""
                INSERT INTO embedding_models (name, provider, api_base, api_key_enc, model_name, dim, request_size, is_enabled)
                VALUES (:name, :provider, :base, :enc, :model, :dim, :req, TRUE)
            """), {
                "name": SEED_NAME,
                "provider": "openai",
                "base": settings.EMBEDDING_API_BASE or "",
                "enc": encrypt_secret(settings.EMBEDDING_API_KEY),
                "model": settings.EMBEDDING_MODEL,
                "dim": dim,
                "req": settings.EMBEDDING_REQUEST_SIZE,
            })
            print(f"已播种向量模型：{settings.EMBEDDING_MODEL}（{dim} 维）")

        if not conn.execute(text(HAS_COL)).scalar():
            conn.execute(text(ADD_COL))
            print("已加列 knowledge_bases.embedding_model_id")
        # 外键列必须有索引：删除模型时 Postgres 要检查引用（RESTRICT），没有索引会全表扫；
        # 列表页的"被几个知识库绑定"也是按这列 group by
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_knowledge_bases_embedding_model_id "
                          "ON knowledge_bases (embedding_model_id)"))

        seed_id = conn.execute(text("SELECT id FROM embedding_models WHERE name = :name"), {"name": SEED_NAME}).scalar()
        if seed_id is None:
            # 表里已有别的模型（有人先手工建过），用最早那个当默认
            seed_id = conn.execute(text("SELECT id FROM embedding_models ORDER BY id LIMIT 1")).scalar()
        if seed_id is None:
            raise SystemExit("中止：embedding_models 里没有任何模型，无法绑定存量知识库")
        result = conn.execute(text(
            "UPDATE knowledge_bases SET embedding_model_id = :mid WHERE embedding_model_id IS NULL"
        ), {"mid": seed_id})
        print(f"已把 {result.rowcount} 个知识库绑到向量模型 id={seed_id}")

        if conn.execute(text(HAS_OLD_COL)).scalar():
            conn.execute(text(DROP_OLD_COL))
            print("已删旧列 knowledge_bases.embedding_model")

        # 绑定完才收紧非空：先加列（可空）→ 回填 → 再 ALTER，否则存量行会让 ALTER 失败
        conn.execute(text("ALTER TABLE knowledge_bases ALTER COLUMN embedding_model_id SET NOT NULL"))
        print("已把 embedding_model_id 收紧为非空")


if __name__ == "__main__":
    main()
