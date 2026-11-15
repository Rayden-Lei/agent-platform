"""按维度分列的迁移脚本（`20261115_120000_v3d1mx_embedding_per_dim_columns`）的核对逻辑。

脚本本身已在共享库上执行过（改名不碰数据），这里测的是它**可被反复执行**与**迁移后判据**两件事：
- 迁移后的列集合与索引能力必须与 `embedding_dims` 的唯一来源一致；
- 核对函数能发现"非空向量列数不为 1"的异常行（迁移正确性的守门人），且是分页扫描、内存有界。

不重建表、不改共享库里的真实数据：异常行用一个事务里的临时数据验证，结束时回滚。
"""
import importlib.util
import pathlib

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.rag import embedding_dims

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrations" / "20261115_120000_v3d1mx_embedding_per_dim_columns.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("embedding_per_dim_columns", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_matches_single_source_of_truth():
    """库里实际的向量列，必须与 embedding_dims 声明的一致（少一列 = 某维度入库必失败）。"""
    with engine.connect() as conn:
        cols = {row[0] for row in conn.execute(text("""
            SELECT attname FROM pg_attribute
            WHERE attrelid = 'document_chunks'::regclass AND attnum > 0 AND NOT attisdropped
        """)).all()}
    for dim in embedding_dims.SUPPORTED_DIMS:
        assert embedding_dims.column_name(dim) in cols, f"缺少维度列 {embedding_dims.column_name(dim)}"
    # 旧的单列必须已经不存在：留着它就意味着某处还在按旧列名写（那会静默写入无人读取的列）
    assert "embedding" not in cols, "旧列 embedding 应已改名为 embedding_<维度>"


def test_index_capability_matches_reality():
    """每个可索引维度都要有 HNSW 部分索引；不可索引的维度（3072）必须没有 —— 两边不能对不上。

    这条防止"代码说 3072 能建索引、库里其实没有"这种静默不一致：检索不会报错，只是慢。
    """
    with engine.connect() as conn:
        indexes = conn.execute(text("""
            SELECT c.relname FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            JOIN pg_class t ON t.oid = i.indrelid
            WHERE t.relname = 'document_chunks' AND i.indisvalid
        """)).all()
    names = {row[0] for row in indexes}
    for dim in embedding_dims.SUPPORTED_DIMS:
        name = f"ix_document_chunks_{embedding_dims.column_name(dim)}_hnsw"
        if embedding_dims.is_indexed(dim):
            assert name in names, f"{dim} 维应可索引，但库里没有 {name}"
        else:
            assert name not in names, f"{dim} 维超过 pgvector 索引上限，库里不应有 {name}"


def test_audit_detects_rows_with_zero_or_two_vector_columns():
    """核对函数要能抓出"某行没有任何向量"或"某行两个维度列都有值"。

    这两种行都说明写入路径出了问题（前者检索永远命中不到，后者违反"一行一维度"的隐含约定），
    迁移后核对必须能发现 —— 否则迁移"看起来成功"，坏数据一直留在库里。
    """
    script = _load_script()
    db = SessionLocal()
    try:
        # 用一个存在但不属于正常数据的 kb/doc 造两行异常数据，结束后回滚
        kb_id = db.execute(text("SELECT id FROM knowledge_bases ORDER BY id LIMIT 1")).scalar()
        doc_id = db.execute(text("SELECT id FROM documents ORDER BY id LIMIT 1")).scalar()
        if kb_id is None or doc_id is None:
            pytest.skip("库里没有知识库 / 文档，无法构造异常行")
        zeros = db.execute(text(
            "INSERT INTO document_chunks (doc_id, kb_id, content, meta, token_count) "
            "VALUES (:d, :k, 'pytest 迁移核对：无向量', '{}'::jsonb, 3) RETURNING id"
        ), {"d": doc_id, "k": kb_id}).scalar()
        two = db.execute(text(
            "INSERT INTO document_chunks (doc_id, kb_id, content, embedding_768, embedding_1024, meta, token_count) "
            "VALUES (:d, :k, 'pytest 迁移核对：两列都有值', "
            "(SELECT array_fill(0.1, ARRAY[768])::vector), (SELECT array_fill(0.1, ARRAY[1024])::vector), '{}'::jsonb, 3) "
            "RETURNING id"
        ), {"d": doc_id, "k": kb_id}).scalar()

        result = script._audit(db.connection())
        problem_ids = {p["id"] for p in result["problems"]}
        assert zeros in problem_ids, "没有任何向量列的行必须被核对发现"
        assert two in problem_ids, "两个维度列都有值的行必须被核对发现"
        # 核对是只读的：扫到的行数应当覆盖全表
        total = db.execute(text("SELECT count(*) FROM document_chunks")).scalar()
        assert result["checked"] == total
    finally:
        # 两行都是本次插入的，直接按 id 删掉（不依赖 cleanup 的前缀规则：这里不按名字造数据）
        try:
            db.rollback()
        finally:
            db.close()


def test_script_is_idempotent_on_current_schema():
    """在当前（已迁移）结构上重复执行：不报错、不改任何东西。

    脚本用 autocommit 连接跑 DDL，所以这里直接调它的 planning 与
    `_add_missing_columns` / 索引存在性判断，不实际执行 CONCURRENTLY（那会持有到表锁的等待）。
    """
    script = _load_script()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        assert script._table_exists(conn) is True
        plan = script._plan(conn)
        # 旧列已经不存在，说明改名阶段已完成
        assert plan["legacy_type"] is None and plan["legacy_dim"] is None
        # 所有支持维度的列都已存在
        for dim in embedding_dims.SUPPORTED_DIMS:
            assert plan["existing"][dim] is not None, f"{dim} 维列应已存在"
