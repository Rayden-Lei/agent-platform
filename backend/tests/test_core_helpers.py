"""核心辅助层的纯函数测试：分页、批量、IP 黑名单。

这三个模块在全仓扫描里是「有实现、零测试」，且都属于**静默失效**类：
- 排序白名单失效 → 用户输入被拼进 order_by（注入面），或翻页结果不稳定
- page_size 没有上限 → 一次请求拉全表
- 批量的逐条独立提交失效 → 一条失败把同批其它条一起回滚
- IP 黑名单解析错 → 静默放行（安全洞）或静默误拦（全站 403）

纯函数，不连库，跑得飞快。
"""
from __future__ import annotations

import pytest

from app.core import ip_filter, pagination
from app.core.batch import BatchIn, run_batch
from app.core.exceptions import BizError


# --------------------------------------------------------------------------- 分页参数

def test_page_size_is_clamped_not_rejected():
    """page_size 超上限按上限截断，不报错 —— 调用方不必知道上限是多少。"""
    p = pagination.page_params(page=1, page_size=10_000)
    assert p.page_size == pagination.PAGE_SIZE_MAX


def test_page_size_max_is_sane():
    """上限本身要够小：没有上限就是"一次请求拉全表"。"""
    assert pagination.PAGE_SIZE_MAX <= 200


def test_page_params_offset():
    assert pagination.PageParams(page=1, page_size=20).offset == 0
    assert pagination.PageParams(page=2, page_size=20).offset == 20
    assert pagination.PageParams(page=5, page_size=10).offset == 40


# --------------------------------------------------------------------------- 排序白名单

class _Dir:
    """排序方向替身：带 key（_id_column 靠它识别主键副键）与方向，不碰真 SQL。

    自己也要有 asc() / desc()：apply_sort 拿到副键后还会再取一次方向。
    """

    def __init__(self, name: str, direction: str):
        self.key = name
        self.direction = direction

    def asc(self):
        return _Dir(self.key, "asc")

    def desc(self):
        return _Dir(self.key, "desc")

    def __repr__(self):
        return f"{self.key}:{self.direction}"


class _Col:
    def __init__(self, name: str):
        self.name = name

    def asc(self):
        return _Dir(self.name, "asc")

    def desc(self):
        return _Dir(self.name, "desc")


class _Q:
    def __init__(self):
        self.ordered = []

    def order_by(self, *cols):
        self.ordered.append(cols)
        return self


def test_apply_sort_uses_whitelisted_field_with_id_tiebreaker():
    """命中白名单时用它排序，并带 id 副键 —— 缺副键时同值行在翻页间会重复或漏掉。"""
    q = _Q()
    pagination.apply_sort(q, pagination.SortParams(sort="name", order="desc"),
                          {"id": _Col("id"), "name": _Col("name")}, [_Col("id").asc()])
    assert len(q.ordered) == 1
    cols = q.ordered[0]
    assert len(cols) == 2, "主排序 + id 副键"
    assert cols[0].key == "name" and cols[0].direction == "desc"
    assert cols[1].key == "id", "必须有 id 副键保证翻页稳定"


def test_apply_sort_rejects_unknown_field_with_400():
    """不在白名单的排序字段返回 400，绝不能静默拼进 SQL（那是注入面）。"""
    q = _Q()
    with pytest.raises(BizError) as ei:
        pagination.apply_sort(q, pagination.SortParams(sort="evil; DROP TABLE x", order="desc"),
                              {"id": _Col("id")}, [_Col("id").asc()])
    assert ei.value.status_code == 400
    assert q.ordered == [], "被拒时不该产生任何排序"


def test_apply_sort_without_params_uses_default():
    """不传 sort 时走接口默认排序。"""
    q = _Q()
    pagination.apply_sort(q, None, {"id": _Col("id")}, [_Col("id").asc()])
    assert len(q.ordered) == 1
    assert q.ordered[0][0].key == "id"


def test_apply_sort_without_params_nor_default_does_not_raise():
    """没有默认排序也不报错（order_by() 无参即清空排序，是 SQLAlchemy 的既定语义）。"""
    q = _Q()
    pagination.apply_sort(q, None, {"id": _Col("id")}, [])
    assert q.ordered == [()]


# --------------------------------------------------------------------------- 批量

class _FakeSession:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def test_run_batch_keeps_going_after_business_failure():
    """逐条独立提交：一条业务失败不该让同批其它条一起回滚。"""
    db = _FakeSession()
    done: list[int] = []

    def act(i: int) -> None:
        if i == 2:
            raise BizError(409, "这一条不行")
        done.append(i)

    result = run_batch(db, [1, 2, 3], act)  # type: ignore[arg-type]
    assert result["succeeded"] == [1, 3]
    assert [f["id"] for f in result["failed"]] == [2]
    assert result["failed"][0]["detail"] == "这一条不行"
    assert db.rollbacks == 1, "失败那条要 rollback，否则 session 不可用"


def test_run_batch_unexpected_error_does_not_leak_internals():
    """非预期异常只回通用文案：日志记全，响应里不能出现内部信息。"""
    db = _FakeSession()

    def act(i: int) -> None:
        raise RuntimeError("数据库密码是 xxx")

    result = run_batch(db, [1], act)  # type: ignore[arg-type]
    assert result["failed"][0]["detail"] == "服务器内部错误"
    assert "密码" not in str(result)


def test_run_batch_empty_list():
    assert run_batch(_FakeSession(), [], lambda i: None) == {"succeeded": [], "failed": []}  # type: ignore[arg-type]


def test_unique_ids_dedupes_and_keeps_first_occurrence_order():
    """前端多选可能传重复 id：只执行一次，且保持首次出现顺序。"""

    class M(BatchIn[str]):
        pass

    assert M(ids=[3, 1, 3, 2, 1], action="delete").unique_ids() == [3, 1, 2]


def test_batch_in_rejects_empty_ids():
    with pytest.raises(Exception):
        BatchIn[str](ids=[], action="delete")


def test_batch_in_rejects_oversized_ids():
    """一次批量有上限，防止把数据库压住。"""
    with pytest.raises(Exception):
        BatchIn[str](ids=list(range(500)), action="delete")


# --------------------------------------------------------------------------- IP 黑名单

def test_parse_networks_supports_cidr_and_bare_ip():
    """CIDR 与裸 IP 都能解析（裸 IP 按 /32）。解析错会静默放行或误拦。"""
    nets = ip_filter._parse_networks("10.0.0.0/8, 192.168.1.5")
    assert len(nets) == 2
    assert str(nets[0]) == "10.0.0.0/8"
    assert str(nets[1]) == "192.168.1.5/32"


def test_parse_networks_skips_blank_entries():
    """空项跳过（配置里常有尾随逗号）。"""
    assert len(ip_filter._parse_networks("10.0.0.0/8, ,")) == 1


def test_parse_networks_empty():
    assert ip_filter._parse_networks("") == ()


def test_is_denied_matches_inside_and_outside():
    assert ip_filter.is_denied("10.9.9.9", "10.0.0.0/8") is True
    assert ip_filter.is_denied("11.0.0.1", "10.0.0.0/8") is False


def test_is_denied_without_denylist_allows_everything():
    assert ip_filter.is_denied("10.9.9.9", "") is False


def test_is_denied_handles_garbage_ip():
    """IP 解析不出来时按未命中处理，不能崩 —— 测试客户端传的就是 "testclient"。"""
    assert ip_filter.is_denied("testclient", "10.0.0.0/8") is False
    assert ip_filter.is_denied(None, "10.0.0.0/8") is False
    assert ip_filter.is_denied("", "10.0.0.0/8") is False
