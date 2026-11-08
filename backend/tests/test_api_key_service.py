"""API Key 鉴权链路与作用域的**服务层**直测（docs/15 3.7.1）。

为什么单独写这一批：`test_api_keys.py` / `test_api_key_scopes.py` 走的是端到端路由，
能证明"某条路径通/不通"，但证明不了**判定顺序**。而顺序在这里是有安全含义的：

    Key 有效 → 归属账号可用 → 来源 IP 白名单 → 限流 → 扣配额

- 白名单/限流放在扣配额**之前**：被拒绝、被限流的请求不消耗配额
  （放反了，攻击者可以拿别人的 Key 狂刷，把正常用户的配额打光）
- 扣配额用带前置条件的 UPDATE（`used < quota`）+ 影响行数判断：
  并发下不会超扣（读-改-写会）
- `_ip_allowed` 在有白名单但判不出来源时**必须拒绝**，不能默认放行

这些性质用路由级用例很难稳定断言，所以直接打服务层。
"""
from __future__ import annotations

import ipaddress
import uuid

import pytest
from sqlalchemy import text

from app.core.exceptions import BizError
from app.db.models import ApiKey, User
from app.db.session import SessionLocal
from app.services import api_key_service


# --------------------------------------------------------------------------- hash_key

def test_hash_key_is_sha256_and_stable():
    """库里只存哈希：同一个明文必须得到同一个哈希，且不可逆（长度固定 64 位十六进制）。"""
    h1 = api_key_service.hash_key("sk-test-abc")
    h2 = api_key_service.hash_key("sk-test-abc")
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)
    # 不同明文不能撞
    assert api_key_service.hash_key("sk-test-abd") != h1


# --------------------------------------------------------------------------- IP 白名单（纯函数）

def test_ip_allowed_empty_list_means_unrestricted():
    """白名单为空 = 不限制来源（这是"没配"的语义，不是"全拒"）。"""
    assert api_key_service._ip_allowed("1.2.3.4", []) is True
    assert api_key_service._ip_allowed(None, []) is True


def test_ip_allowed_matches_exact_and_cidr():
    allowed = ["10.0.0.0/8", "192.168.1.5"]
    assert api_key_service._ip_allowed("10.9.9.9", allowed) is True
    assert api_key_service._ip_allowed("192.168.1.5", allowed) is True
    assert api_key_service._ip_allowed("11.0.0.1", allowed) is False
    assert api_key_service._ip_allowed("192.168.1.6", allowed) is False


def test_ip_allowed_rejects_when_ip_unknown_but_list_present():
    """配了白名单却判不出来源时必须拒绝 —— 宁可拒绝，不能因为"不知道"就默认放行。"""
    assert api_key_service._ip_allowed(None, ["10.0.0.0/8"]) is False
    assert api_key_service._ip_allowed("", ["10.0.0.0/8"]) is False
    assert api_key_service._ip_allowed("not-an-ip", ["10.0.0.0/8"]) is False


def test_ip_allowed_handles_ipv6():
    assert api_key_service._ip_allowed("::1", ["::1/128"]) is True
    assert api_key_service._ip_allowed("2001:db8::1", ["2001:db8::/32"]) is True
    assert api_key_service._ip_allowed("2001:db9::1", ["2001:db8::/32"]) is False


# --------------------------------------------------------------------------- authenticate：五步判定

@pytest.fixture
def make_key():
    """直接在库里造一个 Key（不走路由，避免路由层的校验影响判定顺序的观察）。"""
    created: list[int] = []

    def _make(**kw):
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.username == "admin").first()
            raw = "sk-pytest-" + uuid.uuid4().hex
            ak = ApiKey(
                name=kw.get("name", "pytest-ak-" + uuid.uuid4().hex[:6]),
                key_hash=api_key_service.hash_key(raw),
                key_prefix=raw[:12],
                quota=kw.get("quota", 10),
                used=kw.get("used", 0),
                is_enabled=kw.get("is_enabled", True),
                user_id=kw.get("user_id", owner.id),
                allowed_ips=kw.get("allowed_ips", []),
                rate_limit_per_minute=kw.get("rate_limit_per_minute"),
                agent_ids=kw.get("agent_ids", []),
                workflow_ids=kw.get("workflow_ids", []),
                kb_ids=kw.get("kb_ids", []),
            )
            db.add(ak)
            db.commit()
            db.refresh(ak)
            created.append(ak.id)
            return raw, ak.id
        finally:
            db.close()

    yield _make
    db = SessionLocal()
    try:
        for kid in created:
            row = db.get(ApiKey, kid)
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


def _read(key_id: int) -> ApiKey:
    db = SessionLocal()
    try:
        return db.get(ApiKey, key_id)
    finally:
        db.close()


def test_authenticate_rejects_unknown_key(make_key):
    db = SessionLocal()
    try:
        with pytest.raises(BizError) as ei:
            api_key_service.authenticate(db, "sk-never-issued")
        assert ei.value.status_code == 401
    finally:
        db.close()


def test_authenticate_rejects_disabled_key(make_key):
    """停用的 Key 与不存在的 Key 回同一句话：不告诉对方"这个 Key 存在但被停用了"。"""
    raw, _ = make_key(is_enabled=False)
    db = SessionLocal()
    try:
        with pytest.raises(BizError) as ei:
            api_key_service.authenticate(db, raw)
        assert ei.value.status_code == 401
        assert "无效" in ei.value.detail
    finally:
        db.close()


def test_authenticate_consumes_one_quota(make_key):
    raw, kid = make_key(quota=5, used=0)
    db = SessionLocal()
    try:
        user, ak, _ = api_key_service.authenticate(db, raw)
        assert user.username == "admin"
        assert ak.id == kid
    finally:
        db.close()
    assert _read(kid).used == 1


def test_authenticate_rejects_when_quota_exhausted(make_key):
    """used 已经等于 quota 时 429，且**不再增加** used（不能越扣越多）。"""
    raw, kid = make_key(quota=3, used=3)
    db = SessionLocal()
    try:
        with pytest.raises(BizError) as ei:
            api_key_service.authenticate(db, raw)
        assert ei.value.status_code == 429
        assert "配额" in ei.value.detail
    finally:
        db.close()
    assert _read(kid).used == 3, "配额用尽后 should 不再消耗"


def test_quota_exhaustion_does_not_consume_on_rejection(make_key):
    """被 IP 白名单拒绝的请求**不消耗配额** —— 否则别人拿你的 Key 狂刷就能把配额打光。

    这是判定顺序的直接断言：白名单判在扣配额之前。
    """
    raw, kid = make_key(quota=10, used=0, allowed_ips=["10.0.0.0/8"])
    db = SessionLocal()
    try:
        # 测试客户端来源不是 10.x，会被白名单拒绝
        with pytest.raises(BizError) as ei:
            api_key_service.authenticate(db, raw)
        assert ei.value.status_code == 403
        assert "IP" in ei.value.detail
    finally:
        db.close()
    assert _read(kid).used == 0, "被白名单拒绝不该消耗配额"


def test_ip_rejection_is_audited(make_key):
    """拒绝要留痕：能追溯"谁的 Key 被什么来源拿去调了"。"""
    raw, kid = make_key(allowed_ips=["10.0.0.0/8"])
    db = SessionLocal()
    try:
        with pytest.raises(BizError):
            api_key_service.authenticate(db, raw)
        # 审计写在同一个库里，用独立会话读
    finally:
        db.close()
    db2 = SessionLocal()
    try:
        row = db2.execute(text(
            "select count(*) from audit_logs where action = 'api_key_ip_rejected' and resource_id = :rid"
        ), {"rid": kid}).scalar_one()
        assert row >= 1
    finally:
        db2.close()


def test_authenticate_rejects_when_owner_inactive(make_key):
    """归属账号停用后 Key 立即失效（403），不是 401 —— Key 本身是对的，是账号不能用了。"""
    db = SessionLocal()
    try:
        other = User(
            username="pytest-ak-owner-" + uuid.uuid4().hex[:6],
            password_hash="x", role="caller", is_active=False,
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        uid = other.id
    finally:
        db.close()

    raw, _ = make_key(user_id=uid)
    db = SessionLocal()
    try:
        with pytest.raises(BizError) as ei:
            api_key_service.authenticate(db, raw)
        assert ei.value.status_code == 403
        assert "不可用" in ei.value.detail
    finally:
        db.close()
    db = SessionLocal()
    try:
        db.delete(db.get(User, uid))
        db.commit()
    finally:
        db.close()


def test_authenticate_updates_last_used_at(make_key):
    """成功调用要更新最后使用时间（页面据此判断 Key 是否还在用）。"""
    raw, kid = make_key()
    before = _read(kid).last_used_at
    assert before is None
    db = SessionLocal()
    try:
        api_key_service.authenticate(db, raw)
    finally:
        db.close()
    assert _read(kid).last_used_at is not None


# --------------------------------------------------------------------------- 作用域判定

def test_agent_scope_allows_only_listed(make_key):
    """Key 只能调作用域内的智能体；JWT（api_key 为 None）不受限。"""
    _, kid = make_key(agent_ids=[7, 9])
    ak = _read(kid)
    api_key_service.check_agent_scope(ak, 7)     # 不抛
    with pytest.raises(BizError) as ei:
        api_key_service.check_agent_scope(ak, 8)
    assert ei.value.status_code == 403
    # JWT 请求不受限
    api_key_service.check_agent_scope(None, 12345)


def test_workflow_scope_allows_only_listed(make_key):
    _, kid = make_key(workflow_ids=[3])
    ak = _read(kid)
    api_key_service.check_workflow_scope(ak, 3)
    with pytest.raises(BizError) as ei:
        api_key_service.check_workflow_scope(ak, 4)
    assert ei.value.status_code == 403
    api_key_service.check_workflow_scope(None, 999)


def test_scope_requires_at_least_one_resource():
    """三类作用域全空要 400：没有"空 = 全部放行"的兜底（那是最危险的默认值）。"""
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.username == "admin").first()
        with pytest.raises(BizError) as ei:
            api_key_service._check_scope(db, [], [], [], owner)
        assert ei.value.status_code == 400
        assert "至少授权一个" in ei.value.detail
    finally:
        db.close()


def test_scope_reports_all_missing_ids_within_one_type():
    """同一类资源里缺的 id 要一次列全（而不是一次报一个）。

    注意：**跨类型是逐个报的** —— 智能体、工作流、知识库按顺序各查一次，第一个非空的
    缺失就抛错。这是实现的既定行为（先报智能体，改了再报工作流），不是"一次报全"。
    真要一次报全需要改成先扫三类再统一抛，那是体验优化、不是缺陷，这里只锁定当前契约。
    """
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.username == "admin").first()
        with pytest.raises(BizError) as ei:
            api_key_service._check_scope(db, [99999991, 99999992], [], [], owner)
        assert ei.value.status_code == 400
        assert "99999991" in ei.value.detail and "99999992" in ei.value.detail
        assert "智能体不存在" in ei.value.detail
    finally:
        db.close()


def test_scope_checks_types_in_order_agent_first():
    """类型顺序：智能体 → 工作流 → 知识库。智能体缺了就先报智能体，不会报后面那类。"""
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.username == "admin").first()
        with pytest.raises(BizError) as ei:
            api_key_service._check_scope(db, [99999991], [99999993], [], owner)
        assert "智能体" in ei.value.detail
        assert "工作流" not in ei.value.detail
    finally:
        db.close()


# --------------------------------------------------------------------------- 序列化不泄露

def test_to_dict_never_exposes_plaintext_or_hash(make_key):
    """对外形态只给前缀：明文与哈希都不能出现在任何响应里。"""
    raw, kid = make_key()
    ak = _read(kid)
    d = api_key_service._to_dict(ak, "admin")
    dumped = str(d)
    assert raw not in dumped
    assert ak.key_hash not in dumped
    assert d["key_prefix"] == ak.key_prefix
    # 作用域同时给原始 id 与带名称的清单
    assert "scope" in d and set(d["scope"]) == {"agents", "workflows", "knowledge_bases"}
