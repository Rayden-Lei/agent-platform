"""运行时可调参数 `/system/settings`（2026-09-06）：规格与来源、范围校验、恢复默认、权限、审计、缓存生效。

改的是共享开发库里的 system_settings 表，每个用例结束都把自己改过的键删回默认。
"""
import uuid

import pytest

from app.config import settings
from app.db.session import SessionLocal
from app.services import settings_service

PATH = "/api/v1/system/settings"


@pytest.fixture(autouse=True)
def _clean_settings(client, auth_headers):
    """用例前后把 system_settings **还原成运行前的样子**。

    开发库是共享的，使用者可能正按自己调的参数在导入。**不能简单地"全部重置为默认"** ——
    那会静默抹掉别人页面上改过的值（2026-09-06 踩过：一轮测试把刚设好的每次请求条数删了）。
    先快照，用例结束按快照还原：多出来的行删掉，改过的行写回原值。
    """
    from app.db.models import SystemSetting

    def _snapshot() -> dict:
        db = SessionLocal()
        try:
            return {r.key: r.value for r in db.query(SystemSetting).all()}
        finally:
            db.close()

    before = _snapshot()

    def _restore() -> None:
        db = SessionLocal()
        try:
            for row in db.query(SystemSetting).all():
                if row.key not in before:
                    db.delete(row)
                elif row.value != before[row.key]:
                    row.value = before[row.key]
            for key, value in before.items():
                if db.get(SystemSetting, key) is None:
                    db.add(SystemSetting(key=key, value=value, updated_by="pytest-restore"))
            db.commit()
        finally:
            db.close()
        settings_service.invalidate_cache()

    # 用例内部要的是"干净起点"：先临时清掉，结束再按快照还原
    db = SessionLocal()
    try:
        db.query(SystemSetting).delete()
        db.commit()
    finally:
        db.close()
    settings_service.invalidate_cache()
    yield
    _restore()


def _items(client, headers) -> dict:
    r = client.get(PATH, headers=headers)
    assert r.status_code == 200, r.text
    return {i["key"]: i for i in r.json()["items"]}


def test_list_returns_spec_and_default_source(client, auth_headers):
    body = client.get(PATH, headers=auth_headers).json()
    assert {g["key"] for g in body["groups"]} == {"ingest", "retrieval"}
    items = {i["key"]: i for i in body["items"]}
    assert set(items) == set(settings_service.SPECS)
    concurrency = items["ingest_embed_concurrency"]
    # 没改过时值 = .env 默认值，来源标 default，页面据此显示"默认"
    assert concurrency["source"] == "default" and concurrency["value"] == settings.INGEST_EMBED_CONCURRENCY
    assert concurrency["min"] == 1 and concurrency["max"] == 16 and concurrency["kind"] == "int"
    assert items["rerank_min_score"]["kind"] == "float" and items["rerank_min_score"]["step"] == 0.01
    assert all(i["label"] and i["description"] for i in body["items"])  # 页面上每项都要有说明


def test_update_persists_and_marks_source_db(client, auth_headers):
    r = client.put(PATH, headers=auth_headers, json={"values": {"ingest_embed_concurrency": 6, "rerank_min_score": 0.15}})
    assert r.status_code == 200, r.text
    items = {i["key"]: i for i in r.json()["items"]}
    assert items["ingest_embed_concurrency"]["value"] == 6 and items["ingest_embed_concurrency"]["source"] == "db"
    assert items["ingest_embed_concurrency"]["updated_by"] == "admin" and items["ingest_embed_concurrency"]["updated_at"]
    assert items["rerank_min_score"]["value"] == 0.15
    # 重新查一次仍是新值（真的落库了，不只是回显）
    assert _items(client, auth_headers)["ingest_embed_concurrency"]["value"] == 6
    # 幂等：同样的请求再发一次，结果一致
    again = client.put(PATH, headers=auth_headers, json={"values": {"ingest_embed_concurrency": 6}})
    assert again.status_code == 200 and {i["key"]: i["value"] for i in again.json()["items"]}["ingest_embed_concurrency"] == 6


def test_null_restores_env_default(client, auth_headers):
    client.put(PATH, headers=auth_headers, json={"values": {"rag_top_k": 9}})
    assert _items(client, auth_headers)["rag_top_k"]["value"] == 9
    r = client.put(PATH, headers=auth_headers, json={"values": {"rag_top_k": None}})
    assert r.status_code == 200
    item = {i["key"]: i for i in r.json()["items"]}["rag_top_k"]
    assert item["source"] == "default" and item["value"] == settings.RAG_TOP_K
    db = SessionLocal()
    try:
        from app.db.models import SystemSetting

        assert db.get(SystemSetting, "rag_top_k") is None  # 恢复默认 = 删掉那一行，不是把默认值写进去
    finally:
        db.close()


@pytest.mark.parametrize("values,keyword", [
    ({"ingest_embed_concurrency": 0}, "取值范围"),          # 低于下限
    ({"ingest_embed_concurrency": 17}, "取值范围"),         # 高于上限
    ({"ingest_embed_concurrency": 2.5}, "必须是整数"),      # 整数型不收小数
    ({"rerank_min_score": 1.5}, "取值范围"),               # 小数型也有范围
    ({"ingest_embed_concurrency": "4"}, None),             # 字符串：请求体校验直接 422
    ({"no_such_key": 1}, None),                            # 未知键：请求体校验直接 422
])
def test_invalid_values_are_rejected(client, auth_headers, values, keyword):
    r = client.put(PATH, headers=auth_headers, json={"values": values})
    assert r.status_code in (400, 422), r.text
    if keyword:
        assert keyword in r.json()["detail"]


def test_partial_batch_is_all_or_nothing(client, auth_headers):
    """一批里有一项越界就整批拒绝，不留"改了一半"的中间态。"""
    r = client.put(PATH, headers=auth_headers, json={"values": {"ingest_embed_concurrency": 8, "rag_top_k": 999}})
    assert r.status_code == 400 and "取值范围" in r.json()["detail"]
    assert _items(client, auth_headers)["ingest_embed_concurrency"]["source"] == "default"  # 合法的那项也没落库


def test_empty_values_rejected(client, auth_headers):
    r = client.put(PATH, headers=auth_headers, json={"values": {}})
    assert r.status_code == 400 and "没有要修改" in r.json()["detail"]


def test_developer_can_read_but_not_write(client, auth_headers):
    username = "pytest-set-" + uuid.uuid4().hex[:6]
    u = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "pytest-Passw0rd", "role": "developer"})
    assert u.status_code == 200, u.text
    dev = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"username": username, "password": "pytest-Passw0rd"}).json()["token"]}
    try:
        assert client.get(PATH, headers=dev).status_code == 200  # 开发者能看
        assert client.put(PATH, headers=dev, json={"values": {"rag_top_k": 5}}).status_code == 403  # 但不能改
    finally:
        client.delete(f"/api/v1/users/{u.json()['id']}", headers=auth_headers)


def test_change_is_audited(client, auth_headers):
    client.put(PATH, headers=auth_headers, json={"values": {"rerank_candidates": 20}})
    logs = client.get("/api/v1/audit-logs", headers=auth_headers, params={"resource": "system_setting", "page_size": 5}).json()["items"]
    assert logs and logs[0]["action"] == "update"
    change = logs[0]["detail"]["changes"]["rerank_candidates"]
    assert change["new"] == 20 and change["old"] is None  # 记下改前改后，便于回溯"谁把召回调坏了"


def test_runtime_value_follows_page_change(client, auth_headers):
    """检索路径读的是运行时值：页面改完立刻生效（本进程改的会主动失效缓存）。"""
    assert settings_service.runtime_value("rerank_candidates") == settings.RERANK_CANDIDATES
    client.put(PATH, headers=auth_headers, json={"values": {"rerank_candidates": 7}})
    assert settings_service.runtime_value("rerank_candidates") == 7


def test_out_of_range_row_in_db_is_clamped_not_crashing(client, auth_headers):
    """库里被人手工塞了越界值（或改小了上限）时，读取端夹到范围内，不能让检索或导入起不来。"""
    db = SessionLocal()
    try:
        from app.db.models import SystemSetting

        db.merge(SystemSetting(key="ingest_embed_concurrency", value=999, updated_by="pytest"))
        db.commit()
    finally:
        db.close()
    settings_service.invalidate_cache()
    assert settings_service.runtime_value("ingest_embed_concurrency") == 16  # 夹到上限
    assert _items(client, auth_headers)["ingest_embed_concurrency"]["value"] == 16
