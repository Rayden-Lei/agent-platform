"""运行时可调参数（system_settings 表）：在页面上改、立刻生效，不用改 .env 重启后端。

只收纳"调优型"参数（导入并发与批量、检索召回与重排阈值）。**连接类配置仍走 .env**：
地址与密钥属于部署环境，密钥更不能落到能被读回的接口上（`security.md` 第三节）。

取值优先级：system_settings 表 > `.env` / `config.Settings` 默认值。库里没有的键就是"用默认值"，
页面上按 source 区分（default / db），因此"改回默认"是删掉那一行，而不是把默认值写进去。

生效时机：
- 导入参数在每篇文档**开始处理时**读一次（`ingest_options`），处理中的文档不受影响，避免中途换批大小把进度算错；
- 检索参数每次检索读一次，带 `CACHE_TTL_SECONDS` 秒的进程内缓存（检索是热路径，不能每次查库）。
  共享库上另一台后端改了值，本节点最多 TTL 秒后跟上；本节点自己改会立刻失效缓存。
"""
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.db.models import SystemSetting
from app.db.session import SessionLocal

SOURCE_DEFAULT = "default"
SOURCE_DB = "db"
KIND_INT = "int"
KIND_FLOAT = "float"
# 检索路径读参数的缓存时长：热路径不能每次查库，又要让页面上的改动很快生效
CACHE_TTL_SECONDS = 5.0

GROUPS = {
    "ingest": {"key": "ingest", "label": "文档导入", "description": "对下一篇开始处理的文档生效，处理中的文档不受影响"},
    "retrieval": {"key": "retrieval", "label": "检索与重排", "description": "对之后的每次检索生效（最多 5 秒延迟）"},
}


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    description: str
    group: str
    default_attr: str  # config.Settings 上的属性名，默认值从那里取（即 .env 的值）
    min: float
    max: float
    kind: str = KIND_INT
    step: float = 1
    unit: str = ""


SPECS: dict = {
    # ---- 文档导入 ----
    "ingest_embed_concurrency": SettingSpec(
        "ingest_embed_concurrency", "并发向量化请求数",
        "同时向向量服务发出的请求数。本地 oMLX / vLLM 可开 2～8，云端服务按其限流调整；调大到服务扛不住时会整体变慢。",
        "ingest", "INGEST_EMBED_CONCURRENCY", 1, 16, unit="个"),
    "ingest_write_buffer": SettingSpec(
        "ingest_write_buffer", "写库缓冲批数",
        "已向量化、排队等写库的批数上限。向量化与写库因此可以流水化：写库慢时模型不用停。0 = 向量化完一批写一批（不流水）。",
        "ingest", "INGEST_WRITE_BUFFER", 0, 32, unit="批"),
    "ingest_batch_size": SettingSpec(
        "ingest_batch_size", "每批切片数",
        "一批向量化完成后一次提交入库并推进进度。批越大提交次数越少，但被中断时未提交的量也越大；小文档可以调小到几片。",
        "ingest", "INGEST_BATCH_SIZE", 1, 1000, unit="片"),
    "embedding_request_size": SettingSpec(
        "embedding_request_size", "每次请求条数",
        "单次向量化请求携带的文本条数，不能超过向量服务的单次上限（阿里云百炼 20，本地 oMLX 可 100）。",
        "ingest", "EMBEDDING_REQUEST_SIZE", 1, 500, unit="条"),
    # ---- 检索与重排 ----
    "rag_top_k": SettingSpec(
        "rag_top_k", "每库召回条数",
        "每个知识库每个子查询最终返回的条数，直接决定塞进提示词的引用量。",
        "retrieval", "RAG_TOP_K", 1, 50, unit="条"),
    "rerank_candidates": SettingSpec(
        "rerank_candidates", "重排候选条数",
        "融合召回后送重排模型的候选条数。条数越多召回越全但越慢（0.6B 重排每条约 80 毫秒）。",
        "retrieval", "RERANK_CANDIDATES", 1, 50, unit="条"),
    "rerank_min_score": SettingSpec(
        "rerank_min_score", "重排淘汰阈值",
        "模型重排分低于此值的候选直接淘汰。Qwen3-Reranker 的强相关约 0.99、无关小于 0.01，默认 0.02。",
        "retrieval", "RERANK_MIN_SCORE", 0, 1, kind=KIND_FLOAT, step=0.01),
    "rerank_gap_ratio": SettingSpec(
        "rerank_gap_ratio", "重排断层比例",
        "分数低于榜首这个比例的候选被视为断层之外并淘汰。调大更严格（结果更少更准），调小更宽松。",
        "retrieval", "RERANK_GAP_RATIO", 0, 1, kind=KIND_FLOAT, step=0.01),
    "rerank_timeout": SettingSpec(
        "rerank_timeout", "重排超时",
        "重排服务调用超时秒数，超时退回词法重排并在系统状态里报降级。",
        "retrieval", "RERANK_TIMEOUT", 1, 60, unit="秒"),
}

# 进程内缓存：{key: 值}，供检索热路径使用
_cache: dict | None = None
_cache_at: float = 0.0
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class IngestOptions:
    """入库流水线在一篇文档开始处理时读一次的参数快照。"""

    batch_size: int
    embed_concurrency: int
    write_buffer: int
    embedding_request_size: int


def _default(spec: SettingSpec):
    return _coerce(spec, getattr(settings, spec.default_attr))


def _coerce(spec: SettingSpec, raw):
    """把库里 / .env 里的原始值收敛成合法值：类型不对或越界都夹到范围内，
    一个坏值不能让导入或检索跑不起来（页面上的写入路径另有严格校验，见 update_settings）。"""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(getattr(settings, spec.default_attr))
    value = min(spec.max, max(spec.min, value))
    return int(value) if spec.kind == KIND_INT else round(value, 6)


def _rows(db: Session) -> dict:
    return {row.key: row for row in db.query(SystemSetting).filter(SystemSetting.key.in_(list(SPECS))).all()}


def _values(db: Session) -> dict:
    rows = _rows(db)
    return {key: (_coerce(spec, rows[key].value) if key in rows else _default(spec)) for key, spec in SPECS.items()}


def invalidate_cache() -> None:
    global _cache, _cache_at
    with _cache_lock:
        _cache, _cache_at = None, 0.0


def _cached_values() -> dict:
    """带 TTL 的参数快照，供没有会话在手的热路径（检索、重排）使用。查库失败时退回 .env 默认值，不让检索因此挂掉。"""
    global _cache, _cache_at
    now = time.monotonic()
    with _cache_lock:
        if _cache is not None and now - _cache_at < CACHE_TTL_SECONDS:
            return _cache
    db = SessionLocal()
    try:
        values = _values(db)
    except Exception:  # 库不可用时不能连累检索：用默认值并留痕（system_status 已单独探测数据库）
        import logging

        logging.getLogger(__name__).warning("读取运行时参数失败，本次使用 .env 默认值", exc_info=True)
        values = {key: _default(spec) for key, spec in SPECS.items()}
    finally:
        db.close()
    with _cache_lock:
        _cache, _cache_at = values, time.monotonic()
    return values


def runtime_value(key: str):
    """取一个运行时参数的当前值（带缓存）。给检索 / 重排这类没有会话的调用方用。"""
    return _cached_values()[key]


def _item(spec: SettingSpec, row: SystemSetting | None) -> dict:
    return {
        "key": spec.key, "label": spec.label, "description": spec.description, "group": spec.group,
        "unit": spec.unit, "kind": spec.kind, "step": spec.step, "min": spec.min, "max": spec.max,
        "default": _default(spec),
        "value": _coerce(spec, row.value) if row is not None else _default(spec),
        "source": SOURCE_DB if row is not None else SOURCE_DEFAULT,
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
        "updated_by": row.updated_by if row is not None else None,
    }


def list_settings(db: Session) -> dict:
    """页面用的完整清单：分组说明 + 每项规格、当前值与来源。"""
    rows = _rows(db)
    return {
        "groups": list(GROUPS.values()),
        "items": [_item(spec, rows.get(key)) for key, spec in SPECS.items()],
    }


def ingest_options(db: Session) -> IngestOptions:
    """入库参数快照：每篇文档开始处理时读一次，处理途中不再变。"""
    values = _values(db)
    return IngestOptions(
        batch_size=values["ingest_batch_size"],
        embed_concurrency=values["ingest_embed_concurrency"],
        write_buffer=values["ingest_write_buffer"],
        embedding_request_size=values["embedding_request_size"],
    )


def update_settings(db: Session, user, values: dict) -> dict:
    """批量改参数：值为 null 表示删掉覆盖、回到 .env 默认。未知键或越界值**整批拒绝**（不留一半生效的中间态）。

    幂等：同样的请求重复提交结果一致。成功后写一条审计并失效本进程缓存。
    """
    if not values:
        raise BizError(400, "没有要修改的参数")
    changes: dict = {}
    for key, raw in values.items():
        spec = SPECS.get(key)
        if spec is None:
            raise BizError(400, f"未知参数：{key}")
        if raw is None:
            changes[key] = None
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise BizError(400, f"{spec.label} 必须是数字")
        if spec.kind == KIND_INT and not float(raw).is_integer():
            raise BizError(400, f"{spec.label} 必须是整数")
        if raw < spec.min or raw > spec.max:
            raise BizError(400, f"{spec.label} 取值范围 {spec.min}～{spec.max}")
        changes[key] = int(raw) if spec.kind == KIND_INT else round(float(raw), 6)
    rows = _rows(db)
    detail: dict = {}
    username = getattr(user, "username", None)
    now = datetime.now(timezone.utc)
    for key, value in changes.items():
        row = rows.get(key)
        old = _coerce(SPECS[key], row.value) if row is not None else None
        if value is None:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(SystemSetting(key=key, value=value, updated_at=now, updated_by=username))
        else:
            row.value = value
            row.updated_at = now
            row.updated_by = username
        detail[key] = {"old": old, "new": value}
    db.commit()
    invalidate_cache()
    record_audit(db, user, "update", "system_setting", None, detail={"changes": detail})
    return list_settings(db)
