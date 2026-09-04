"""列表接口统一分页：参数解析 + 查询切页。契约见 docs/04-接口设计.md 第 2.3 节。

- page 从 1 起；page_size 默认 20，超过上限按上限截断而不是报错，调用方不必知道上限。
- 排序由各服务自己指定（必须带唯一副键，通常是 id），这里只负责 count / offset / limit。
"""
from dataclasses import dataclass
from typing import Callable

from fastapi import Query

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, description=f"每页条数，上限 {PAGE_SIZE_MAX}"),
) -> PageParams:
    return PageParams(page=page, page_size=min(page_size, PAGE_SIZE_MAX))


def paginate(query, params: PageParams, serialize: Callable = lambda row: row) -> dict:
    """对已带排序的 SQLAlchemy Query 切页。total 用去掉排序的子查询计数，避免无谓的排序开销。"""
    total = query.order_by(None).count()
    rows = query.offset(params.offset).limit(params.page_size).all()
    return {"items": [serialize(r) for r in rows], "total": total, "page": params.page, "page_size": params.page_size}
