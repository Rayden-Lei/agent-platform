"""向量模型服务的**校验与分支**（embedding_model_service）。

与 test_embedding_models.py 的分工：那个文件走接口，覆盖"建/改/停用/删除"的主链路；
这里直接对服务层下断言，专攻**拒绝路径与副作用**：
维度与请求条数的边界、改配置后必须清客户端缓存、密钥永不出现在对外形态里。

为什么值得单独测：
- 维度校验错一处，错误就跑到后台入库线程里（用户只看到文档 failed，毫无线索）；
- 清了缓存才会生效，不清的表现为"页面上改了、重启才好"——这类静默失效最难排查；
- 密钥泄漏是不可逆的，只回 has_key 这条必须有用例钉住。
"""
from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import BizError
from app.db.models import EmbeddingModel
from app.db.session import SessionLocal
from app.rag import embedding_dims, embeddings
from app.services import embedding_model_service as svc


class _Payload:
    """替代 pydantic 入参：服务层只按属性取值，用例不必构造完整 schema。"""

    def __init__(self, **kw):
        self.name = kw.get("name", "pytest-emb-" + uuid.uuid4().hex[:6])
        self.provider = kw.get("provider", "openai")
        self.api_base = kw.get("api_base", "https://pytest.invalid/v1")
        self.api_key = kw.get("api_key", "sk-pytest-secret")
        self.model_name = kw.get("model_name", "pytest-embed")
        self.dim = kw.get("dim", 1024)
        self.request_size = kw.get("request_size", 16)
        self.is_enabled = kw.get("is_enabled", True)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def admin(db):
    from app.db.models import User

    return db.query(User).filter(User.username == "admin").first()


@pytest.fixture
def made(db, admin):
    """造一个向量模型并在结束时删掉（不依赖 cleanup 的宽限期，用例自己能收尾）。"""
    created: list[int] = []

    def _make(**kw) -> EmbeddingModel:
        data = svc.create_model(db, _Payload(**kw), admin)
        db.commit()
        created.append(data["id"])
        return db.get(EmbeddingModel, data["id"])

    yield _make
    for model_id in created:
        row = db.get(EmbeddingModel, model_id)
        if row is not None:
            db.delete(row)
            db.commit()


# --------------------------------------------------------------------------- 维度校验

@pytest.mark.parametrize("dim", [768, 1024, 1536, 3072])
def test_supported_dims_pass(dim):
    """支持集合里的每个维度都要能过 —— 少一个就等于那个维度的模型永远建不了。"""
    svc._check_dim(dim)


@pytest.mark.parametrize("dim", [0, -1, 4097, 10000])
def test_dim_out_of_range_rejected(dim):
    with pytest.raises(BizError) as ei:
        svc._check_dim(dim)
    assert ei.value.status_code == 422
    assert "维度必须在" in ei.value.detail


@pytest.mark.parametrize("dim", [100, 512, 2048])
def test_dim_in_range_but_unsupported_rejected(dim):
    """范围内但没有对应向量列的维度必须拒：否则入库写切片时才炸，而那是后台线程。"""
    with pytest.raises(BizError) as ei:
        svc._check_dim(dim)
    assert ei.value.status_code == 422
    assert "不支持的向量维度" in ei.value.detail
    # 报错里要列出可选值，使用者才知道该改成多少
    assert str(dim) in ei.value.detail
    for supported in embedding_dims.SUPPORTED_DIMS:
        assert str(supported) in ei.value.detail


def test_dim_check_matches_the_column_set():
    """校验用的集合必须就是切片表有列的那个集合：两处各写一份就会分叉。"""
    for dim in embedding_dims.SUPPORTED_DIMS:
        svc._check_dim(dim)
    assert not embedding_dims.is_supported(2048)


# --------------------------------------------------------------------------- 请求条数

@pytest.mark.parametrize("size", [1, 16, 500])
def test_request_size_bounds_accepted(size):
    svc._check_request_size(size)


@pytest.mark.parametrize("size", [0, -1, 501])
def test_request_size_out_of_bounds_rejected(size):
    with pytest.raises(BizError) as ei:
        svc._check_request_size(size)
    assert ei.value.status_code == 422
    assert "单次请求条数" in ei.value.detail


# --------------------------------------------------------------------------- 对外形态

def test_to_dict_never_exposes_the_key(made):
    """密钥只回 has_key：明文与密文都不许出现在对外形态里。"""
    row = made(api_key="sk-super-secret-never-leak")
    out = svc._to_dict(row)
    assert out["has_key"] is True
    assert "sk-super-secret-never-leak" not in str(out)
    assert "api_key" not in out and "api_key_enc" not in out


def test_to_dict_reports_no_key_when_absent(made):
    row = made()
    row.api_key_enc = None
    assert svc._to_dict(row)["has_key"] is False


def test_create_requires_api_key(db, admin):
    with pytest.raises(BizError) as ei:
        svc.create_model(db, _Payload(api_key="   "), admin)
    assert ei.value.status_code == 422
    assert "API Key" in ei.value.detail


def test_create_rejects_duplicate_name(db, admin, made):
    row = made()
    with pytest.raises(BizError) as ei:
        svc.create_model(db, _Payload(name=row.name), admin)
    assert ei.value.status_code == 400
    assert "已存在" in ei.value.detail


# --------------------------------------------------------------------------- 更新与缓存

def test_update_clears_client_cache_when_config_changes(made, db, admin, monkeypatch):
    """改了地址/模型名必须清客户端缓存，否则进程里还拿着旧配置，表现为"改了不生效"。"""
    cleared = {"n": 0}
    monkeypatch.setattr(embeddings, "clear_client_cache", lambda: cleared.__setitem__("n", cleared["n"] + 1))
    row = made()
    svc.update_model(db, row.id, _Payload(name=row.name, model_name="changed-model", dim=row.dim), admin)
    assert cleared["n"] == 1


def test_update_clears_client_cache_when_key_rotated(made, db, admin, monkeypatch):
    cleared = {"n": 0}
    monkeypatch.setattr(embeddings, "clear_client_cache", lambda: cleared.__setitem__("n", cleared["n"] + 1))
    row = made()
    svc.update_model(db, row.id, _Payload(name=row.name, api_key="sk-new"), admin)
    assert cleared["n"] == 1


def test_update_does_not_clear_cache_when_nothing_changed(made, db, admin, monkeypatch):
    """没改任何东西就清缓存会让正在进行的入库重新建连接，纯属浪费。"""
    cleared = {"n": 0}
    monkeypatch.setattr(embeddings, "clear_client_cache", lambda: cleared.__setitem__("n", cleared["n"] + 1))
    row = made()
    svc.update_model(db, row.id, _Payload(name=row.name, api_key=""), admin)
    assert cleared["n"] == 0


def test_update_empty_key_keeps_existing(made, db, admin):
    """api_key 传空表示沿用已有密钥（编辑页不回显密钥，不能因为留空就把密钥清掉）。"""
    row = made(api_key="sk-original")
    before = row.api_key_enc
    svc.update_model(db, row.id, _Payload(name=row.name, api_key=""), admin)
    db.refresh(row)
    assert row.api_key_enc == before


def test_update_rejects_duplicate_name(made, db, admin):
    first, second = made(), made()
    with pytest.raises(BizError) as ei:
        svc.update_model(db, second.id, _Payload(name=first.name), admin)
    assert ei.value.status_code == 400


def test_update_missing_model_is_404(db, admin):
    with pytest.raises(BizError) as ei:
        svc.update_model(db, 99999999, _Payload(), admin)
    assert ei.value.status_code == 404


# --------------------------------------------------------------------------- 停用 / 删除

def test_toggle_blocks_disable_when_bound(made, db, admin):
    """被知识库绑定的模型不能停用：停用后那些库既不能入库也不能检索，且库的模型不可改。"""
    from app.db.models import KnowledgeBase

    row = made()
    kb = KnowledgeBase(name="pytest-emb-kb-" + uuid.uuid4().hex[:6], description="",
                       embedding_model_id=row.id, chunk_size=200, chunk_overlap=0, created_by=admin.id)
    db.add(kb)
    db.commit()
    try:
        with pytest.raises(BizError) as ei:
            svc.toggle_model(db, row.id, admin)
        assert ei.value.status_code == 400
        assert "仍有知识库绑定" in ei.value.detail
    finally:
        db.delete(kb)
        db.commit()


def test_toggle_unbound_works_both_ways(made, db, admin):
    row = made()
    assert svc.toggle_model(db, row.id, admin)["is_enabled"] is False
    assert svc.toggle_model(db, row.id, admin)["is_enabled"] is True


def test_delete_blocks_when_bound(made, db, admin):
    """被绑定时 409 并点名库名：外键 RESTRICT 也会拦，但那条报错看不懂。"""
    from app.db.models import KnowledgeBase

    row = made()
    kb = KnowledgeBase(name="pytest-emb-kb2-" + uuid.uuid4().hex[:6], description="",
                       embedding_model_id=row.id, chunk_size=200, chunk_overlap=0, created_by=admin.id)
    db.add(kb)
    db.commit()
    try:
        with pytest.raises(BizError) as ei:
            svc.delete_model(db, row.id, admin)
        assert ei.value.status_code == 409
        assert kb.name in ei.value.detail
    finally:
        db.delete(kb)
        db.commit()


def test_delete_missing_is_404(db, admin):
    with pytest.raises(BizError) as ei:
        svc.delete_model(db, 99999999, admin)
    assert ei.value.status_code == 404


def test_get_missing_is_404(db):
    with pytest.raises(BizError) as ei:
        svc.get_model(db, 99999999)
    assert ei.value.status_code == 404
