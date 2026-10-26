"""db.session.rows_to_dict：两列结果集转 dict（不碰数据库，直接喂元组序列）。"""
from app.db.session import rows_to_dict


def test_rows_to_dict_builds_mapping():
    assert rows_to_dict([(1, "admin"), (2, "developer")]) == {1: "admin", 2: "developer"}


def test_rows_to_dict_keeps_last_value_on_duplicate_key():
    """group by 出来的 key 本来就唯一；真重复时按后到的覆盖，与 dict() 行为一致。"""
    assert rows_to_dict([(1, "a"), (1, "b")]) == {1: "b"}


def test_rows_to_dict_empty():
    assert rows_to_dict([]) == {}
