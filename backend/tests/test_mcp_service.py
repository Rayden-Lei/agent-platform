"""MCP 服务器的地址与凭据校验（services/mcp_service.py 的 _check_* 与 update_server 凭据分支）。

为什么单独测：MCP 服务器的地址是**外部输入**，而平台会主动去连它。
- allowed_hosts **不允许为空**：没配白名单就无从判断目标是否可信，等于闸门不存在；
- 密钥必须走 secret 字段（加密落库），写进 headers 等于明文进库、还会出现在接口返回里；
- 更新时"不传沿用 / 传了更换 / clear_secret 清除"三条分支错一条，要么密钥丢失要么改不掉。

纯函数与内存对象为主，不连真实 MCP server。
"""
from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import BizError
from app.db.models import McpServer, User
from app.db.session import SessionLocal
from app.services import mcp_service as svc


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def admin(db):
    return db.query(User).filter(User.username == "admin").first()


class _Payload:
    def __init__(self, **kw):
        self.name = kw.get("name", "pytest-mcp-" + uuid.uuid4().hex[:6])
        self.description = kw.get("description", "")
        self.transport = kw.get("transport", "streamable_http")
        self.url = kw.get("url", "https://mcp.example.test/mcp")
        self.headers = kw.get("headers", {})
        self.secret = kw.get("secret", "")
        self.clear_secret = kw.get("clear_secret", False)
        self.allowed_hosts = kw.get("allowed_hosts", ["mcp.example.test"])
        self.is_enabled = kw.get("is_enabled", True)


@pytest.fixture
def made(db, admin):
    created: list[int] = []

    def _make(**kw) -> McpServer:
        data = svc.create_server(db, _Payload(**kw), admin)
        created.append(data["id"])
        return db.get(McpServer, data["id"])

    yield _make
    for sid in created:
        row = db.get(McpServer, sid)
        if row is not None:
            db.delete(row)
            db.commit()


# --------------------------------------------------------------------------- 地址校验

@pytest.mark.parametrize("url", [
    "https://mcp.example.test/mcp",
    "http://127.0.0.1:8080/sse",
])
def test_valid_url_passes(url):
    svc._check_url(url)


@pytest.mark.parametrize("url,fragment", [
    ("ftp://mcp.example.test/x", "http://"),
    ("file:///etc/passwd", "http://"),
    ("mcp.example.test/x", "http://"),
    ("https://", "缺少主机名"),
])
def test_bad_url_rejected(url, fragment):
    """只允许 http / https：stdio 与其他协议都不该出现在这里。"""
    with pytest.raises(BizError) as ei:
        svc._check_url(url)
    assert ei.value.status_code == 400
    assert fragment in ei.value.detail


# --------------------------------------------------------------------------- 白名单校验

def test_allowed_hosts_required():
    """**空名单必须拒**：MCP 地址由管理员配，没白名单就无从判断目标是否可信。
    这与内置 http_request"空名单只拦内网"不同，理由写在该函数的 docstring 里。"""
    for empty in ([], None):
        with pytest.raises(BizError) as ei:
            svc._check_allowed_hosts(empty)
        assert "必须配置 allowed_hosts" in ei.value.detail
    # 全是空白串：走的是"每一项必须非空"那条（同样拒，只是文案不同）
    with pytest.raises(BizError) as ei:
        svc._check_allowed_hosts([""])
    assert "非空字符串" in ei.value.detail


def test_allowed_hosts_normalized_to_lowercase():
    assert svc._check_allowed_hosts(["MCP.Example.Test", " api.x.com "]) == ["mcp.example.test", "api.x.com"]


@pytest.mark.parametrize("bad", ["https://x.com", "x.com:8080", "x.com/path"])
def test_allowed_hosts_rejects_scheme_port_path(bad):
    """只写域名：带协议、端口或路径会让匹配规则失效（"填了却不生效且不报错"）。"""
    with pytest.raises(BizError) as ei:
        svc._check_allowed_hosts([bad])
    assert "不是合法主机名" in ei.value.detail


def test_allowed_hosts_rejects_non_list():
    with pytest.raises(BizError) as ei:
        svc._check_allowed_hosts("x.com")
    assert "必须是数组" in ei.value.detail


def test_allowed_hosts_rejects_too_many():
    with pytest.raises(BizError) as ei:
        svc._check_allowed_hosts([f"h{i}.com" for i in range(svc.MAX_ALLOWED_HOSTS + 1)])
    assert "最多" in ei.value.detail


def test_allowed_hosts_rejects_overlong_host():
    with pytest.raises(BizError) as ei:
        svc._check_allowed_hosts(["a" * 256])
    assert "不是合法主机名" in ei.value.detail


# --------------------------------------------------------------------------- 密钥不能进 headers

def test_secret_in_headers_is_rejected(db, admin):
    """密钥写进 headers 等于明文落库、还会出现在接口返回里：必须引导到 secret 字段。"""
    with pytest.raises(BizError) as ei:
        svc.create_server(db, _Payload(headers={"Authorization": "Bearer sk-leak"}), admin)
    assert ei.value.status_code == 400
    assert "不要写进请求头" in ei.value.detail
    assert "Authorization" in ei.value.detail


def test_plain_header_is_allowed(db, admin, made):
    """非密钥类请求头（如自定义标识）照常允许。"""
    row = made(headers={"X-Client": "agent-platform"})
    assert row.headers == {"X-Client": "agent-platform"}


# --------------------------------------------------------------------------- 创建与重名

def test_duplicate_name_rejected(db, admin, made):
    row = made()
    with pytest.raises(BizError) as ei:
        svc.create_server(db, _Payload(name=row.name), admin)
    assert ei.value.status_code == 409
    assert "已存在" in ei.value.detail


def test_get_missing_is_404(db):
    with pytest.raises(BizError) as ei:
        svc.get_server(db, 99999999)
    assert ei.value.status_code == 404


def test_to_dict_never_exposes_secret(made):
    """对外形态只回 has_secret：密文与明文都不出现。"""
    row = made(secret="sk-mcp-super-secret")
    out = svc._to_dict(row)
    assert out["has_secret"] is True
    assert "sk-mcp-super-secret" not in str(out)
    assert "secret_enc" not in out


# --------------------------------------------------------------------------- 更新时的凭据三分支

def test_update_without_secret_keeps_it(made, db, admin):
    """不传 secret 表示沿用：编辑页不回显密钥，留空不能把密钥清掉。"""
    row = made(secret="sk-original")
    before = row.secret_enc
    svc.update_server(db, row.id, _Payload(name=row.name, secret=""), admin)
    db.refresh(row)
    assert row.secret_enc == before


def test_update_with_secret_replaces_it(made, db, admin):
    row = made(secret="sk-old")
    before = row.secret_enc
    svc.update_server(db, row.id, _Payload(name=row.name, secret="sk-new"), admin)
    db.refresh(row)
    assert row.secret_enc != before
    from app.core.security import decrypt_secret

    assert decrypt_secret(row.secret_enc) == "sk-new"


def test_update_clear_secret_removes_it(made, db, admin):
    """clear_secret 显式清除：与"留空沿用"是两件事，不能混。"""
    row = made(secret="sk-to-clear")
    svc.update_server(db, row.id, _Payload(name=row.name, secret="", clear_secret=True), admin)
    db.refresh(row)
    assert row.secret_enc is None


def test_update_clear_secret_when_already_empty_is_noop(made, db, admin):
    row = made()
    svc.update_server(db, row.id, _Payload(name=row.name, clear_secret=True), admin)
    db.refresh(row)
    assert row.secret_enc is None


def test_update_rejects_duplicate_name(made, db, admin):
    first, second = made(), made()
    with pytest.raises(BizError) as ei:
        svc.update_server(db, second.id, _Payload(name=first.name), admin)
    assert ei.value.status_code == 409


def test_update_validates_url_and_hosts(made, db, admin):
    """更新走同一套校验：不能因为"只是改个地址"就绕过白名单。"""
    row = made()
    with pytest.raises(BizError):
        svc.update_server(db, row.id, _Payload(name=row.name, url="ftp://x"), admin)
    with pytest.raises(BizError):
        svc.update_server(db, row.id, _Payload(name=row.name, allowed_hosts=[]), admin)


def test_update_missing_is_404(db, admin):
    with pytest.raises(BizError) as ei:
        svc.update_server(db, 99999999, _Payload(), admin)
    assert ei.value.status_code == 404


# --------------------------------------------------------------------------- 启停

def test_set_enabled_toggles(made, db, admin):
    row = made()
    assert svc.set_enabled(db, row.id, False, admin)["is_enabled"] is False
    assert svc.set_enabled(db, row.id, True, admin)["is_enabled"] is True


def test_set_enabled_missing_is_404(db, admin):
    with pytest.raises(BizError):
        svc.set_enabled(db, 99999999, True, admin)
