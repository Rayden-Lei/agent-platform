"""列表接口统一分页：参数解析 + 查询切页。契约见 docs/04-接口设计.md 第 2.3 节。

- page 从 1 起；page_size 默认 20，超过上限按上限截断而不是报错，调用方不必知道上限。
- 排序由各服务自己指定（必须带唯一副键，通常是 id），这里只负责 count / offset / limit。
"""
from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import Query

from app.core.exceptions import BizError

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


@dataclass(frozen=True)
class PageParams:
    """分页参数值对象（不可变）：page 从 1 起，offset 由两者计算得出。"""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        """跳过前 (page-1)*page_size 行，作为 SQL offset。"""
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, description=f"每页条数，上限 {PAGE_SIZE_MAX}"),
) -> PageParams:
    """FastAPI 依赖：解析查询参数并夹紧 page_size（超过上限按上限截断，不报错）。"""
    return PageParams(page=page, page_size=min(page_size, PAGE_SIZE_MAX))


@dataclass(frozen=True)
class SortParams:
    """排序参数值对象：sort 为字段名（各列表接口自带白名单），order 为 asc / desc；sort 为空走接口默认排序。"""

    sort: str | None
    order: str

    @property
    def desc(self) -> bool:
        return self.order == "desc"


def sort_params(
    sort: str | None = Query(None, max_length=32, description="排序字段，取值见各接口说明"),
    order: Literal["asc", "desc"] = Query("desc", description="排序方向"),
) -> SortParams:
    """FastAPI 依赖：解析排序参数。字段是否合法由 apply_sort 按白名单判断（400），方向在这里就限定枚举（422）。"""
    return SortParams(sort=sort, order=order)


def apply_sort(query, params: SortParams | None, allowed: dict, default):
    """按白名单排序：sort 命中 allowed 才用它（并带 id 副键保证翻页稳定），不在白名单 400，为空走 default。

    allowed 形如 {"started_at": Run.started_at}，default 是 order_by 的参数列表（必须自带唯一副键）。
    字段名不能拼进 SQL，白名单是防注入的唯一手段。
    """
    if params is None or not params.sort:
        return query.order_by(*default)
    column = allowed.get(params.sort)
    if column is None:
        raise BizError(400, f"不支持的排序字段：{params.sort}，可选 {', '.join(allowed)}")
    primary = column.desc() if params.desc else column.asc()
    tie_breaker = _id_column(default)
    return query.order_by(primary, tie_breaker.desc() if params.desc else tie_breaker.asc()) if tie_breaker is not None else query.order_by(primary)


def time_range(start, end) -> tuple:
    """时间区间参数的统一校验：两端都必须带时区（naive 值与 timestamptz 比较结果取决于会话时区，静默出错），
    且 start 必须早于 end；区间语义左闭右开 [start, end)。不合法 400。"""
    for name, value in (("起始时间", start), ("结束时间", end)):
        if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
            raise BizError(400, f"{name}必须带时区，例如 2026-09-06T00:00:00+08:00")
    if start is not None and end is not None and start >= end:
        raise BizError(400, "起始时间必须早于结束时间")
    return start, end


def _id_column(default):
    """从默认排序里找出主键副键（通常是 <Model>.id），排序字段相同的行靠它保证顺序确定。"""
    for item in default:
        element = getattr(item, "element", item)
        if getattr(element, "key", None) == "id":
            return element
    return None


def paginate(query, params: PageParams, serialize: Callable = lambda row: row) -> dict:
    """对已带排序的 SQLAlchemy Query 切页。total 用去掉排序的子查询计数，避免无谓的排序开销。"""
    total = query.order_by(None).count()
    rows = query.offset(params.offset).limit(params.page_size).all()
    return {"items": [serialize(r) for r in rows], "total": total, "page": params.page, "page_size": params.page_size}
