"""能力型内置工具（tools/general.py）与运行时配置的联动。

覆盖三件最容易出错的事：
1. SSRF 防护：模型能构造任意 URL，内网地址必须拦死（这里只测纯函数，不发真实请求）；
2. 配置优先级：页面写的值优先于 .env，改完下一次调用即生效；
3. 密钥脱敏：secret 类型的明文永远不出现在接口返回与审计里。
"""
import pytest

from app.services import settings_service
from app.tools import general


# --------------------------------------------------------------------------- 纯函数

def test_text_stats_counts_cjk_and_latin_separately():
    """中文按字、英文按词：单纯按空格切词会把整段中文算成 1 个词。"""
    r = general.text_stats("Hello world 你好世界")
    assert r["char_count"] == 16          # "Hello world " 12 + 4 个汉字
    assert r["word_count"] == 2 + 4      # 2 个英文词 + 4 个汉字
    assert r["line_count"] == 1


def test_text_stats_rejects_oversize():
    """超长输入直接拒绝，不让它把内存吃穿。"""
    r = general.text_stats("x" * (general.TEXT_MAX_CHARS + 1))
    assert "error" in r


def test_random_int_respects_range():
    """边界值必须可达，且反区间要报错而不是静默返回。"""
    assert general.random_int(5, 5)["result"] == 5
    assert "error" in general.random_int(10, 1)


def test_random_choice_splits_on_newline_and_comma():
    r = general.random_choice("a,b\nc")
    assert r["result"] in {"a", "b", "c"}
    assert "error" in general.random_choice("  ")


def test_base64_roundtrip():
    enc = general.base64_encode("你好")
    assert general.base64_decode(enc["result"])["result"] == "你好"


def test_base64_decode_rejects_garbage():
    assert "error" in general.base64_decode("这不是base64!!")


def test_json_query_walks_path():
    doc = '{"data":{"items":[{"name":"x"}]}}'
    assert general.json_query(doc, "data.items[0].name")["result"] == "x"
    assert general.json_query(doc, "")["result"] == {"data": {"items": [{"name": "x"}]}}


def test_json_query_reports_missing_field_with_available_keys():
    """错误信息要能帮模型自己纠正：告诉它有哪些字段可选。"""
    r = general.json_query('{"a":1}', "b")
    assert "error" in r
    assert "a" in r["error"]


def test_json_query_index_out_of_range():
    assert "error" in general.json_query('{"a":[1]}', "a[5]")


# --------------------------------------------------------------------------- SSRF

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/health",
    "http://192.168.121.85:5433/",
    "http://10.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",   # 云元数据服务，最典型的 SSRF 目标
])
@pytest.mark.anyio
async def test_http_request_blocks_private_addresses(url):
    """内网与元数据地址一律拦死：模型能构造任意 URL，这是唯一的防线。"""
    r = await general.http_request(url)
    assert "error" in r
    assert "内网" in r["error"]


@pytest.mark.anyio
async def test_http_request_rejects_non_http_scheme():
    r = await general.http_request("file:///etc/passwd")
    assert "error" in r


# --------------------------------------------------------------------------- 配置

def test_tool_reads_runtime_setting_over_env(db, monkeypatch):
    """页面写入的值优先于 .env：工具通过 _cfg 读，改完下一次调用即生效。"""
    admin = _admin(db)
    settings_service.update_settings(db, admin, {"search_default_limit": 2})
    settings_service.invalidate_cache()
    try:
        assert general._cfg("search_default_limit") == 2
    finally:
        settings_service.update_settings(db, admin, {"search_default_limit": None})
        settings_service.invalidate_cache()


def test_secret_value_never_echoed(db):
    """密钥写入后，接口只给 configured 与掩码，明文不出现在返回里。"""
    admin = _admin(db)
    secret = "sk-verify-never-echoed-123456"
    settings_service.update_settings(db, admin, {"search_api_key": secret})
    try:
        item = _item(db, "search_api_key")
        assert item["configured"] is True
        assert item["value"] is None
        assert secret not in str(item)
        assert item["masked"].startswith("sk-v")
        assert item["masked"].endswith("56")
    finally:
        settings_service.update_settings(db, admin, {"search_api_key": None})


def test_secret_not_written_to_audit_in_plaintext(db):
    """审计日志能被管理员读回，密钥明文绝不能进去。"""
    from sqlalchemy import text

    admin = _admin(db)
    secret = "sk-audit-leak-check-abcdef"
    settings_service.update_settings(db, admin, {"search_api_key": secret})
    try:
        detail = db.execute(text(
            "select detail from audit_logs where action='update' and resource='system_setting' "
            "order by id desc limit 1"
        )).scalar()
        assert secret not in str(detail)
    finally:
        settings_service.update_settings(db, admin, {"search_api_key": None})


def test_text_setting_rejects_non_string(db):
    with pytest.raises(settings_service.BizError):
        settings_service.update_settings(db, _admin(db), {"search_endpoint": 123})


def test_unknown_setting_rejected(db):
    with pytest.raises(settings_service.BizError):
        settings_service.update_settings(db, _admin(db), {"no_such_key": 1})


# --------------------------------------------------------------------------- 辅助

def _admin(db):
    from app.db.models import User

    return db.query(User).filter(User.username == "admin").first()


def _item(db, key: str) -> dict:
    return next(i for i in settings_service.list_settings(db)["items"] if i["key"] == key)


@pytest.fixture
def db():
    from app.db.session import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
