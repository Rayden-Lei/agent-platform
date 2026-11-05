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


# --------------------------------------------------------------------------- 工具级配置

def test_tool_config_reads_from_tool_row_over_default():
    """配置属于工具：工具行里的值优先于代码默认值，同一平台的两个工具可各配各的。"""
    conf = {"default_limit": 3, "max_limit": 8}
    assert general.tool_config("web_search", conf, "default_limit") == 3
    assert general.tool_config("web_search", conf, "max_limit") == 8
    # 没配的键回落到 TOOL_CONFIG_DEFAULTS
    assert general.tool_config("web_search", conf, "timeout") == 20
    assert general.tool_config("web_search", {}, "default_limit") == 5


def test_tool_config_two_tools_differ():
    """两个 web_search 工具各带自己的 config，互不影响——这正是"配置放工具页"的理由。"""
    a = {"default_limit": 2, "max_limit": 4}
    b = {"default_limit": 9, "max_limit": 10}
    assert general.tool_config("web_search", a, "default_limit") == 2
    assert general.tool_config("web_search", b, "default_limit") == 9


def test_config_fields_declared_for_tools():
    """要能被工具页渲染，必须有声明；secret 项要标出来，否则前端当普通文本框。"""
    from app.tools.tool_config import TOOL_CONFIG_FIELDS

    search = {f.key: f for f in TOOL_CONFIG_FIELDS["web_search"]}
    assert search["api_key"].kind == "secret"
    assert search["endpoint"].kind == "str"
    assert search["default_limit"].kind == "int"


def test_secret_never_leaves_via_config_out(db):
    """工具行里的密钥加密存 secret_enc，_config_out 只给 has_secret，绝不下发明文。"""
    from app.core.security import encrypt_secret
    from app.db.models import Tool
    from app.services.tool_service import _config_out

    secret = "sk-tool-owned-never-leaked-9999"
    t = db.query(Tool).filter(Tool.name == "web_search").first()
    original = (dict(t.config or {}), t.secret_enc)
    try:
        t.config = {**(t.config or {}), "default_limit": 3}
        t.secret_enc = encrypt_secret(secret)
        db.commit()
        out = _config_out(t)
        assert secret not in str(out), "明文出现在接口返回里"
        assert out.get("default_limit") == 3
        assert any(f["kind"] == "secret" for f in out["config_fields"])
    finally:
        t.config, t.secret_enc = original
        db.commit()


def test_settings_service_no_longer_owns_tool_config():
    """工具配置不该再出现在系统参数里——这是使用者指出的职责错位。"""
    assert not any(k.startswith("search_") or k.startswith("http_") for k in settings_service.SPECS)
    groups = {g["key"] for g in settings_service.GROUPS.values()}
    assert "tools" not in groups


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
