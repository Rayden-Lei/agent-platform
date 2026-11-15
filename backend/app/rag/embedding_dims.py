"""切片向量的「按维度分列」：让同一实例里不同知识库能绑定不同维度的向量模型。

## 为什么是"多列"而不是"按维度分表"

pgvector 的向量列是定长的（`vector(N)`），一列只能装一个维度，而 `document_chunks.embedding`
原来是硬编码的 `vector(settings.EMBEDDING_DIM)`，于是整个实例只能有一个维度。两种解法：

1. **多列**（本方案）：`document_chunks` 上加 `embedding_768 / embedding_1024 / embedding_1536 /
   embedding_3072` 各一列，每行只有与该库模型维度一致的那一列有值，每列配一个只收非空行的
   部分 HNSW 索引（`WHERE 该列 IS NOT NULL`）。
2. **按维度分表**：`document_chunks_768 / _1024 / ...`，应用层按维度路由，或用 ORM 继承。

选多列，理由按重要性排：

- **存量数据零拷贝**。改造前 `document_chunks.embedding` 已经是 `vector(1024)`，迁移里
  `ALTER TABLE ... RENAME COLUMN embedding TO embedding_1024` 一句就够 —— 数据不重写、
  不重建索引、迁移秒级完成。分表方案要把存量切片逐行搬进新表，每搬一次都要维护外键与
  id 序列，还要处理"搬到一半失败"的部分状态；切片表是所有表里增长最快的一张，
  这类搬迁在真实规模上是停机级操作。
- **所有与向量无关的读取路径一行不改**。`kb_service.list_document_chunks`、
  按库 `chunk_count` 分组统计、`delete_document` 级联删切片、`pipeline._resume_start` 的
  已入库计数、按 `doc_id` 删除、前端切片抽屉，全部继续打同一张表。分表方案里这些
  都要变成跨表 UNION 或按维度路由，等于把"支持多维度"这个局部需求扩散到整个知识库模块。
- **检索结果的身份不变**。一条切片仍是一行，`id` 全局唯一，`chunk_id` 仍能直接定位，
  引用（citations）与前端不需要感知维度。分表会让 id 在表间重复，引用得带维度才解得开。
- **写入只有一处分支**。`pipeline._write_batch` 按 `spec.dim` 选列写、其余列留 NULL。
  分表方案要引入继承或工厂，还要解决"库换维度后旧切片怎么搬"。

代价与取舍（都是明确接受了的）：

- 表上多出 3 个大多为 NULL 的向量列。pgvector 的 NULL 在变长存储里几乎不占空间，
  当前规模可忽略；真到几百万行，可在运维层按维度归档，不影响本设计的正确性。
- **3072 维建不了 ANN 索引**：本机与云端都是 pgvector **0.6.0**，HNSW 与 IVFFlat 的硬上限
  都是 2000 维（实测报 `column cannot have more than 2000 dimensions for hnsw index`）。
  仍然支持 3072（text-embedding-3-large 就是 3072 维，拒掉它等于任务没做完），
  但代价必须可见：`is_indexed(3072)` 为 False，模型表单与列表会标注"检索为顺序扫描"。
  将来两套环境都升到 pgvector ≥ 0.7 时，这一列可改用 `halfvec(3072)` 建索引。
- **没有 CHECK 约束兜底"一列非空"**：加约束意味着以后新增维度还要再改一次约束，
  而判据在检索侧本来就够严 —— 查询按库的维度选列并带 `IS NOT NULL`，别的列有值也读不到。
  代价是理论上允许一行两列都有值；写入路径只有 pipeline 一处且按维度单写，构造不出来。

## 支持的维度只在这里定义

`SUPPORTED_DIMS` 是唯一来源：服务端保存向量模型时校验它（权威），
`GET /embedding-models/dims` 把它下发给前端渲染下拉（体验）。
不在集合里的维度一律拒绝 —— 否则会等到入库写切片时才发现"没有这一列"，
错误出现在后台线程里，用户只看到文档 failed。
"""
from __future__ import annotations

# 支持的维度。顺序即前端下拉顺序；1024 是当前存量切片的维度（迁移把 embedding 列改名而来）。
SUPPORTED_DIMS: tuple[int, ...] = (768, 1024, 1536, 3072)

# pgvector 0.6 的 ANN 索引（HNSW / IVFFlat）维度上限。超过它的列只能顺序扫描：
# 仍然支持该维度（功能可用），但要在界面上标注出来，否则"检索突然变慢"无从排查。
INDEX_MAX_DIM = 2000


def is_supported(dim: int) -> bool:
    """维度是否受支持。服务端保存模型、入库写切片前的唯一判据。"""
    return dim in SUPPORTED_DIMS


def is_indexed(dim: int) -> bool:
    """该维度能否建 ANN 索引。False 表示检索走顺序扫描（功能正常、代价是慢）。"""
    return is_supported(dim) and dim <= INDEX_MAX_DIM


def column_name(dim: int) -> str:
    """维度 → document_chunks 上的列名。"""
    return f"embedding_{dim}"


def all_column_names() -> tuple[str, ...]:
    """全部向量列名。检索要 defer 掉它们：一条 1536 维向量 6KB，上百条候选全拉回来毫无用处。"""
    return tuple(column_name(d) for d in SUPPORTED_DIMS)


def orm_column(dim: int):
    """维度 → DocumentChunk 的 ORM 列对象（用于 cosine_distance 与 IS NOT NULL 过滤）。

    不支持时直接抛 ValueError 而不是返回 None：调用方拿到 None 只会在更远的地方
    以更难懂的方式炸（AttributeError），这里当场失败并带上可用维度。
    """
    from app.db.models import DocumentChunk

    if not is_supported(dim):
        raise ValueError(f"不支持的向量维度 {dim}：可选 {list(SUPPORTED_DIMS)}")
    return getattr(DocumentChunk, column_name(dim))


def defer_options() -> list:
    """全部向量列的 defer 选项，供 select 直接展开使用（`select(...).options(*embedding_dims.defer_options())`）。

    为什么不返回列对象让调用方自己写 `defer(*cols)`：SQLAlchemy 2.0 把多参数 defer 当成
    relationship 加载路径解析，传列对象会报 "Mapped attribute ... does not refer to a mapped entity"。
    每个列单独一个 defer 才是正确写法，把这个易错点收在唯一定义维度列名的地方。
    """
    from sqlalchemy.orm import defer

    from app.db.models import DocumentChunk

    return [defer(getattr(DocumentChunk, name)) for name in all_column_names()]


def default_dim() -> int:
    """表单新模型的预填维度：优先用 .env 配的 EMBEDDING_DIM（全局兜底模型的实际维度），
    它不在支持集合里时退回 1024（存量切片维度的历史默认值）。"""
    from app.config import settings

    return settings.EMBEDDING_DIM if is_supported(settings.EMBEDDING_DIM) else 1024


def describe() -> dict:
    """下发给前端的形态（GET /embedding-models/dims）：扁平列表 + 预填维度 + 可索维度。

    indexed_dims 单独给一份，前端据此在"维度"旁标注"检索为顺序扫描"，
    不用自己复制 2000 这个 pgvector 版本相关的常数。
    """
    return {
        "dims": list(SUPPORTED_DIMS),
        "indexed_dims": [d for d in SUPPORTED_DIMS if is_indexed(d)],
        "default_dim": default_dim(),
        "index_max_dim": INDEX_MAX_DIM,
    }
