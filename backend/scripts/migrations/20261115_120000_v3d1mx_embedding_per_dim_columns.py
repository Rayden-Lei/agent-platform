"""迁移（2026-11-15）：切片向量按维度分列，让同一实例支持不同维度的向量模型。

改什么
------
1. `document_chunks.embedding`（`vector(EMBEDDING_DIM)` 定长列）改名为 `embedding_<当前维度>`，
   并去掉 NOT NULL —— 这是纯元数据操作，不重写数据、不丢向量，任意规模都是秒级。
2. 补齐 `embedding_768 / embedding_1024 / embedding_1536 / embedding_3072` 四列（可空），缺哪列加哪列。
3. 每个受支持维度建一个**部分 HNSW 索引**（cosine，`WHERE embedding_<dim> IS NOT NULL`），
   CONCURRENTLY + lock_timeout，不阻塞读写。3072 维不建索引（pgvector 0.6 上限 2000 维）。
4. **顺带补上从来就不存在的向量索引**：docs/09 与迁移 `20260906_190000` 都写着"HNSW 已完成"，
   但实库里 `document_chunks` 上只有 3 个 btree 索引（pkey / doc_id / kb_id），
   没有任何 hnsw 或 ivfflat —— 那个脚本从没在这套库上成功执行过。也就是说向量检索一直是全表扫描。
   本脚本按维度列把索引建起来；这是"原本就该有但缺失的"，不是本次改造引入的。

为什么
------
`09-演进路线.md` 第 4 节登记：`document_chunks.embedding` 是定长的 `vector(1024)`，pgvector
一列一个维度，装不下别的维度，于是 2026-11-08 那次改造只能在保存模型时拦住维度不一致的模型（422）
—— 这是绕开问题而不是解决问题。现在每个支持的维度各占一列，入库与检索按知识库绑定的模型选列。
选型理由（为什么多列而不是按维度分表）见 `backend/app/rag/embedding_dims.py` 的文件注释。

影响
----
- 结构：1 列改名 + 3 列新增 + 3 个部分 HNSW 索引。
- 数据：**零丢失**。改名不动数据；存量切片的向量本来就在当前列宽的维度上，改名后落在正确的那一列。
- 存量切片不用重建，检索结果与迁移前一致（同一个向量、同一个余弦距离，只是列名变了）。
- 写库：迁移期间正在入库的文档若撞上改名会失败一次，重跑续处理即可（pipeline 支持续处理）。
- 执行顺序：**先跑本脚本，再部署新后端**。新代码按新列名查询，结构没改就部署会 500；
  反之旧代码在改名后会找不到 `embedding` 列，同样 500。两边必须在同一个窗口切换。
- 执行后：后端需重启（ORM 变了）。云端同样要跑一遍，否则云端仍是旧结构。

幂等
----
- 列改名：先查 `information_schema` / `pg_attribute`，已是新列名就跳过；旧列不存在时不做任何事。
- 加列：`ADD COLUMN IF NOT EXISTS`；新列都是可空的，存量行自动为 NULL，不需要回填。
- 索引：`CREATE INDEX CONCURRENTLY IF NOT EXISTS`；上次中断留下的 INVALID 索引先删再建
  （与 `20260906_190000` / `20260906_193000` 两个脚本同一写法）。
- 重复执行第二次：0 行变更、索引全部 EXISTS 直接跳过。

分批
----
本脚本没有需要逐行改写的数据（改名不碰数据），所以没有回填批次。索引用 CONCURRENTLY 建，
不锁表。迁移后的核对（向量维度是否都落在正确的列上）用 keyset 分页按 id 扫描，
不把整表拉进内存 —— 切片表是全库增长最快的一张，核对也必须是 O(1) 内存。

执行
----
    cd backend && .venv/bin/python scripts/migrations/20261115_120000_v3d1mx_embedding_per_dim_columns.py            # 预览
    cd backend && .venv/bin/python scripts/migrations/20261115_120000_v3d1mx_embedding_per_dim_columns.py --apply    # 执行
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db.session import engine
from app.rag.embedding_dims import INDEX_MAX_DIM, SUPPORTED_DIMS, column_name, is_indexed

TABLE = "document_chunks"
# 改造前的列名。它承载着当前列宽那个维度的存量向量。
LEGACY_COLUMN = "embedding"

# 扫描核对时的每批行数：只取 id 与维度，一批一批走，内存与表规模无关。
AUDIT_BATCH = 5000


def _column_type(conn, column: str) -> str | None:
    """列的实际类型（如 vector(1024)）；列不存在返回 None。"""
    return conn.execute(text("""
        SELECT format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = :t AND a.attname = :c AND a.attnum > 0 AND NOT a.attisdropped
    """), {"t": TABLE, "c": column}).scalar()


def _column_dim(conn, column: str) -> int | None:
    """向量列的实际维度。pgvector 把维度存在 atttypmod 里，原样就是维度（不用像早期脚本那样减 8 ——
    那个减 8 的写法是给 numeric 之类类型用的，对 pgvector 是错的，见 docs/09 第 4 节最后一条）。"""
    row = conn.execute(text("""
        SELECT a.atttypmod FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = :t AND a.attname = :c AND a.attnum > 0 AND NOT a.attisdropped
    """), {"t": TABLE, "c": column}).scalar()
    return int(row) if row and row > 0 else None


def _has_column(conn, column: str) -> bool:
    return _column_type(conn, column) is not None


def _table_exists(conn) -> bool:
    """全新库（应用还没启动过、create_all 没跑）里这张表可能不存在。

    这种环境按 models.py 建表自然就是新结构，本脚本无事可做 —— 但必须先查出来，
    否则 `count(*)` 直接 UndefinedTable，让"重复执行应当无副作用"这条失效。
    """
    return bool(conn.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{TABLE}"}).scalar())


def _plan(conn) -> dict:
    """收集现状，供预览与执行共用（预览不写库）。"""
    legacy_type = _column_type(conn, LEGACY_COLUMN)
    legacy_dim = _column_dim(conn, LEGACY_COLUMN) if legacy_type else None
    existing = {d: _column_type(conn, column_name(d)) for d in SUPPORTED_DIMS}
    total = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar() or 0
    return {"legacy_type": legacy_type, "legacy_dim": legacy_dim, "existing": existing, "rows": total}


def _rename_legacy(conn, legacy_dim: int) -> None:
    """把改造前的列改名为它维度对应的新列名，并去掉 NOT NULL。

    只改元数据：数据、向量、行 id 全部原地不动，没有拷贝也没有重建。
    必须去 NOT NULL：同一行现在只有一列有值，其余维度列是 NULL，旧列在部分行上会是 NULL。
    """
    target = column_name(legacy_dim)
    conn.execute(text(f"ALTER TABLE {TABLE} RENAME COLUMN {LEGACY_COLUMN} TO {target}"))
    conn.execute(text(f"ALTER TABLE {TABLE} ALTER COLUMN {target} DROP NOT NULL"))
    print(f"已把 {LEGACY_COLUMN} 改名为 {target}（维度 {legacy_dim}），数据未拷贝")


def _add_missing_columns(conn) -> None:
    for dim in SUPPORTED_DIMS:
        name = column_name(dim)
        if _has_column(conn, name):
            continue
        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {name} vector({dim})"))
        print(f"已加列 {name} vector({dim})")


def _index_name(dim: int) -> str:
    return f"ix_{TABLE}_{column_name(dim)}_hnsw"


def _drop_invalid_index(conn, name: str) -> None:
    """上次中断留下的 INVALID 索引：pgvector 的 HNSW 建到一半被杀会留这个，直接重跑会报已存在。"""
    invalid = conn.execute(text("""
        SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
        WHERE c.relname = :n AND NOT i.indisvalid
    """), {"n": name}).scalar()
    if invalid:
        print(f"发现上次中断留下的无效索引 {name}，先删除重建")
        conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))


def _legacy_index(conn) -> str | None:
    """改造前那个不分维度的 HNSW 索引名（迁移 20260906_190000 里定义的）。存在就返回它。

    实库里当前没有它（脚本从没成功执行过），但别的环境可能有 —— 它建在旧列上，
    改名后会自动跟着变成 embedding_<dim> 列上的索引，与按维度建的索引重复。
    """
    name = f"ix_{TABLE}_embedding_hnsw"
    return name if conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar() else None


def _create_dim_indexes(conn, legacy_dim: int | None) -> None:
    """每个可索引维度建一个部分 HNSW 索引（只收该列非空的行）。

    部分索引而不是全量索引：同一行只有一列有值，全量索引里绝大多数键是 NULL；
    按维度建部分索引让"这个库用哪些行"直接体现在索引谓词上，索引本身也小得多。

    3072 维不建：pgvector 0.6 的 HNSW/IVFFlat 上限是 2000 维（实测报
    "column cannot have more than 2000 dimensions for hnsw index"）。该维度检索走顺序扫描。
    """
    legacy = _legacy_index(conn)
    for dim in SUPPORTED_DIMS:
        name = _index_name(dim)
        if not is_indexed(dim):
            print(f"跳过 {name}：{dim} 维超过 pgvector 的 ANN 索引上限 {INDEX_MAX_DIM}，"
                  f"该维度检索走顺序扫描（功能正常，代价是慢）")
            continue
        # 旧索引正好落在改名前那一列（现在叫 embedding_<legacy_dim>）上：改名即可，不必重建
        if legacy and dim == legacy_dim and not conn.execute(
                text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar():
            conn.execute(text(f"ALTER INDEX {legacy} RENAME TO {name}"))
            print(f"旧索引 {legacy} 已改名为 {name}（同一列，不重建）")
            legacy = None
            continue
        _drop_invalid_index(conn, name)
        started = time.time()
        conn.execute(text(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {TABLE} "
            f"USING hnsw ({column_name(dim)} vector_cosine_ops) WHERE {column_name(dim)} IS NOT NULL"
        ))
        size = conn.execute(text("SELECT pg_size_pretty(pg_relation_size(:n))"), {"n": name}).scalar()
        print(f"HNSW 索引 {name} 就绪，大小 {size}，耗时 {time.time() - started:.0f}s")
    if legacy:
        # 旧索引既不是按维度建的、也没能改名沿用：留着只是多一份写放大，删掉
        print(f"删除不分维度的旧索引 {legacy}（已由按维度索引取代）")
        conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {legacy}"))


def _audit(conn) -> dict:
    """迁移后核对：每行的非空向量列必须恰好一个，且维度与该列声明一致。keyset 分页，内存 O(1)。

    只读，不改数据。返回 {"checked": 行数, "problems": [...]}（problems 最多带 10 条样本）。
    """
    checked = 0
    problems: list = []
    last_id = 0
    nonnull_expr = " + ".join(
        f"CASE WHEN {column_name(d)} IS NOT NULL THEN 1 ELSE 0 END" for d in SUPPORTED_DIMS
    )
    while True:
        rows = conn.execute(text(f"""
            SELECT id, ({nonnull_expr}) AS n
            FROM {TABLE} WHERE id > :last ORDER BY id LIMIT :lim
        """), {"last": last_id, "lim": AUDIT_BATCH}).all()
        if not rows:
            break
        for row_id, count in rows:
            checked += 1
            if count != 1:
                problems.append({"id": row_id, "reason": f"非空向量列数={count}，应恰好为 1"})
        last_id = rows[-1][0]
        if len(problems) >= 10:
            break
    return {"checked": checked, "problems": problems[:10]}


def main() -> None:
    apply_changes = "--apply" in sys.argv
    # CONCURRENTLY 不能跑在事务里：用 autocommit 连接，并设 lock_timeout（导入进行中拿不到锁就退出）
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SET lock_timeout = '5s'"))

        if not _table_exists(conn):
            print(f"{TABLE} 不存在：全新库按 models.py 建表就是新结构，本脚本无事可做")
            return

        plan = _plan(conn)
        legacy_dim = plan["legacy_dim"]
        print(f"{TABLE}：{plan['rows']} 行")
        print(f"旧列 {LEGACY_COLUMN}：{plan['legacy_type'] or '已不存在'}"
              + (f"（维度 {legacy_dim}）" if legacy_dim else ""))
        for dim in SUPPORTED_DIMS:
            name = column_name(dim)
            print(f"  列 {name}: {plan['existing'][dim] or '待加'}"
                  + ("（将建 HNSW）" if is_indexed(dim) else "（不建 HNSW：超过 pgvector 上限）"))

        if not apply_changes:
            print("以上为预览，未写库；确认后加 --apply 执行")
            return

        # 1. 旧列改名（纯元数据）。维度不在支持集合里时中止：说明这套库的列宽与代码支持的范围不一致，
        #    盲目改名会造出一个代码不认识、也查不到的列，数据就等于丢了。
        if legacy_dim is not None:
            if legacy_dim not in SUPPORTED_DIMS:
                raise SystemExit(
                    f"中止：{LEGACY_COLUMN} 的实际维度是 {legacy_dim}，不在支持集合 {list(SUPPORTED_DIMS)} 里。"
                    "先把该维度加进 app/rag/embedding_dims.SUPPORTED_DIMS 再重跑，不要直接改名。"
                )
            _rename_legacy(conn, legacy_dim)

        # 2. 补齐其余维度列
        _add_missing_columns(conn)

        # 3. 索引（顺带补上从来就不存在的向量索引）
        _create_dim_indexes(conn, legacy_dim)

        # 4. 核对
        result = _audit(conn)
        print(f"核对：扫描 {result['checked']} 行，问题 {len(result['problems'])} 处"
              + (f"：{result['problems']}" if result["problems"] else ""))
        print("完成。执行后需重启后端（ORM 变了），云端也要跑一遍本脚本。")


if __name__ == "__main__":
    main()
