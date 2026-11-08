"""登录锁定、手机号脱敏、改密与退出其他设备的直测（docs/15 OP-03 / OP-04）。

扫描时这个模块是「有实现、零直接测试」。它守的是几件**出错会静默**的事：

- 连续失败 5 次锁 10 分钟 —— 写错就变成了无限暴力破解，或者把正常用户锁死
- Redis 故障时降级放行（可用性优先），但状态要被记录下来并能在页面上看到
- 手机号只露前 3 后 4，不足 8 位全遮 —— 漏了就是个人信息泄露
- 改密 / 退出其他设备要递增 token_version，让旧令牌立即失效

Redis 相关用例用真实 Redis（测试库），不全打桩 —— 打桩就测不到 key 的拼写与过期时间。
"""
from __future__ import annotations

import uuid

import pytest

from app.core import redis_client
from app.core.exceptions import BizError
from app.db.models import User
from app.db.session import SessionLocal
from app.services import auth_service

PASSWORD = "pw-" + uuid.uuid4().hex[:12]


@pytest.fixture
def temp_user():
    """造一个可用账号，用完删掉。密码哈希走真实实现。"""
    from app.core.security import hash_password

    created: list[int] = []

    def _make(**kw):
        db = SessionLocal()
        try:
            u = User(
                username=kw.get("username", "pytest-auth-" + uuid.uuid4().hex[:8]),
                password_hash=hash_password(kw.get("password", PASSWORD)),
                role=kw.get("role", "caller"),
                is_active=kw.get("is_active", True),
                token_version=kw.get("token_version", 0),
            )
            db.add(u)
            db.commit()
            db.refresh(u)
            uid = u.id
            created.append(uid)
            out = {"id": uid, "username": u.username, "password": kw.get("password", PASSWORD)}
            return out
        finally:
            db.close()

    yield _make
    db = SessionLocal()
    try:
        for uid in created:
            row = db.get(User, uid)
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_login_fail():
    """每个用例前后清掉失败计数，避免相互污染（这个 key 是全局的，按用户名分）。"""
    client = redis_client.get_redis()
    if client is not None:
        for k in client.keys("login_fail:pytest-*"):
            client.delete(k)
        for k in client.keys("pwchange_fail:*"):
            client.delete(k)
    yield
    if client is not None:
        for k in client.keys("login_fail:pytest-*"):
            client.delete(k)
        for k in client.keys("pwchange_fail:*"):
            client.delete(k)


# --------------------------------------------------------------------------- 手机号脱敏

def test_mask_phone_keeps_first3_last4():
    assert auth_service.mask_phone("13812345678") == "138****5678"


def test_mask_phone_hides_short_numbers_entirely():
    """不足 8 位时全遮：否则"露前 3 后 4"会把整个号码都露出来。"""
    assert auth_service.mask_phone("1234567") == "****"
    assert auth_service.mask_phone("123") == "****"
    assert auth_service.mask_phone("12345678") == "123****5678"   # 刚好 8 位：前 3 后 4，中间重叠由 **** 覆盖


def test_mask_phone_none():
    assert auth_service.mask_phone(None) is None
    assert auth_service.mask_phone("") is None


# --------------------------------------------------------------------------- 登录

def test_login_success_issues_token_and_updates_last_login(temp_user):
    u = temp_user()
    db = SessionLocal()
    try:
        out = auth_service.login(db, u["username"], u["password"])
        assert out.token
        assert out.user.username == u["username"]
    finally:
        db.close()
    db = SessionLocal()
    try:
        row = db.get(User, u["id"])
        assert row.last_login_at is not None
    finally:
        db.close()


def test_login_wrong_password_is_401_and_counts_a_failure(temp_user):
    u = temp_user()
    db = SessionLocal()
    try:
        with pytest.raises(BizError) as ei:
            auth_service.login(db, u["username"], "wrong-password")
        assert ei.value.status_code == 401
        # 不能泄露"用户存在但密码错"与"用户不存在"的区别
        assert "用户名或密码错误" == ei.value.detail
    finally:
        db.close()
    client = redis_client.get_redis()
    if client is not None:
        assert int(client.get(auth_service._fail_key(u["username"])) or 0) == 1


def test_login_unknown_user_counts_under_that_username():
    """不存在的用户名同样计数：否则攻击者可以先枚举用户名再针对性爆破。"""
    name = "pytest-auth-ghost-" + uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        with pytest.raises(BizError) as ei:
            auth_service.login(db, name, "whatever")
        assert ei.value.status_code == 401
    finally:
        db.close()
    client = redis_client.get_redis()
    if client is not None:
        assert int(client.get(auth_service._fail_key(name)) or 0) == 1


def test_login_locks_after_max_failures(temp_user):
    """连续失败达到上限后，即使密码正确也返回 429 —— 这是暴力破解保护的存在意义。"""
    u = temp_user()
    client = redis_client.get_redis()
    if client is None:
        pytest.skip("Redis 不可用，锁定相关的用例无法验证")
    key = auth_service._fail_key(u["username"])
    client.set(key, auth_service.MAX_LOGIN_FAIL)
    client.expire(key, auth_service.LOCK_SECONDS)

    db = SessionLocal()
    try:
        with pytest.raises(BizError) as ei:
            auth_service.login(db, u["username"], u["password"])   # 密码是对的
        assert ei.value.status_code == 429
        assert "次数过多" in ei.value.detail
    finally:
        db.close()


def test_login_success_clears_failure_count(temp_user):
    """登录成功后清空计数：历史失败不能累积到把正常用户锁死。"""
    u = temp_user()
    db = SessionLocal()
    try:
        with pytest.raises(BizError):
            auth_service.login(db, u["username"], "wrong")
    finally:
        db.close()
    client = redis_client.get_redis()
    if client is None:
        pytest.skip("Redis 不可用")
    assert int(client.get(auth_service._fail_key(u["username"])) or 0) == 1

    db = SessionLocal()
    try:
        auth_service.login(db, u["username"], u["password"])
    finally:
        db.close()
    assert client.get(auth_service._fail_key(u["username"])) is None


def test_fail_count_has_expiry(temp_user):
    """失败计数必须带过期时间，否则一次错误会被永久记住。"""
    u = temp_user()
    client = redis_client.get_redis()
    if client is None:
        pytest.skip("Redis 不可用")
    db = SessionLocal()
    try:
        with pytest.raises(BizError):
            auth_service.login(db, u["username"], "wrong")
    finally:
        db.close()
    ttl = client.ttl(auth_service._fail_key(u["username"]))
    assert 0 < ttl <= auth_service.LOCK_SECONDS


def test_login_rejects_inactive_account(temp_user):
    """账号停用返回 403（密码对也是 403）：与"密码错"区分开，便于用户理解。"""
    u = temp_user(is_active=False)
    db = SessionLocal()
    try:
        with pytest.raises(BizError) as ei:
            auth_service.login(db, u["username"], u["password"])
        assert ei.value.status_code == 403
        assert "停用" in ei.value.detail
    finally:
        db.close()


def test_login_guard_status_reports_enabled():
    """状态接口要能说明"暴力破解保护当前是否生效"：Redis 挂了这里应该是 enabled=False。"""
    st = auth_service.login_guard_status()
    assert st["max_fail"] == auth_service.MAX_LOGIN_FAIL
    assert st["lock_seconds"] == auth_service.LOCK_SECONDS
    assert isinstance(st["enabled"], bool)
    if st["enabled"]:
        assert st["reason"] is None
    else:
        assert st["reason"]


# --------------------------------------------------------------------------- token_version 失效

def test_logout_others_bumps_token_version(temp_user):
    """退出其他设备：token_version +1，此前签发的令牌全部失效。"""
    u = temp_user(token_version=3)
    db = SessionLocal()
    try:
        row = db.get(User, u["id"])
        out = auth_service.logout_others(db, row)
        assert out.token
        db.refresh(row)
        assert row.token_version == 4
    finally:
        db.close()


def test_change_password_bumps_token_version_and_verifies_old(temp_user):
    """改密要校验原密码；成功后 token_version 递增，旧令牌失效。"""
    u = temp_user()
    db = SessionLocal()
    try:
        row = db.get(User, u["id"])
        before = row.token_version
        new_pw = "new-" + uuid.uuid4().hex[:10]
        out = auth_service.change_password(db, row, u["password"], new_pw)
        assert out.token
        db.refresh(row)
        assert row.token_version == before + 1
        # 新密码真的生效了
        auth_service.login(db, u["username"], new_pw)
    finally:
        db.close()


def test_change_password_rejects_wrong_old_password(temp_user):
    u = temp_user()
    db = SessionLocal()
    try:
        row = db.get(User, u["id"])
        with pytest.raises(BizError) as ei:
            auth_service.change_password(db, row, "not-the-password", "whatever-" + uuid.uuid4().hex[:8])
        assert ei.value.status_code == 400 or ei.value.status_code == 401
    finally:
        db.close()


# --------------------------------------------------------------------------- 资料更新

def test_update_profile_only_touches_provided_fields(temp_user):
    """只改请求里带了的字段：没传的不能被动成 None。"""
    u = temp_user()
    db = SessionLocal()
    try:
        row = db.get(User, u["id"])
        row.email = "keep@example.com"
        db.commit()

        from app.schemas import ProfileUpdateIn

        auth_service.update_profile(db, row, ProfileUpdateIn(display_name="新名字"))
        db.refresh(row)
        assert row.display_name == "新名字"
        assert row.email == "keep@example.com"
    finally:
        db.close()


def test_profile_of_masks_phone_and_exposes_public_base_url(temp_user):
    """对外资料里手机号只能是脱敏值 —— 完整手机号不该出现在任何响应里。"""
    u = temp_user()
    db = SessionLocal()
    try:
        row = db.get(User, u["id"])
        row.phone = "13900001111"
        db.commit()
        me = auth_service.profile_of(row)
        assert me.phone_masked == "139****1111"
        assert "13900001111" not in str(me.model_dump())
    finally:
        db.close()
