"""个人中心（docs/15 OP-03，AC-033 ⑤）：本人资料、退出其他设备、登录记录、我的 API 密钥，以及管理员代发 Key（D-15）。
本人改密的用例在 test_account_security.py（OP-04）。
"""
import uuid

import pytest

from app.db.models import AuditLog
from app.db.session import SessionLocal

ME = "/api/v1/auth/me"
KEYS = "/api/v1/api-keys"
PASSWORD = "pytest-Passw0rd"


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def made(client, auth_headers):
    """登记本用例建的 Key 与用户，结束时先删 Key 再删用户。"""
    bag = {"keys": [], "users": []}
    yield bag
    for kind, path in (("keys", KEYS), ("users", "/api/v1/users")):
        for oid in bag[kind]:
            client.delete(f"{path}/{oid}", headers=auth_headers)


def _user(client, auth_headers, made, role: str = "caller") -> tuple[dict, dict]:
    username = f"pytest-me-{role}-{_uid()}"
    u = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": PASSWORD, "role": role})
    assert u.status_code == 200, u.text
    made["users"].append(u.json()["id"])
    token = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}).json()["token"]
    return u.json(), {"Authorization": "Bearer " + token}


def _key(client, headers, made, key_scope, **extra) -> dict:
    r = client.post(KEYS, headers=headers, json={"name": "pytest-me-key-" + _uid(), **key_scope, **extra})
    if r.status_code == 200:
        made["keys"].append(r.json()["id"])
    return r


# ---------- 资料 ----------

def test_profile_update_changes_only_given_fields_and_masks_phone(client, auth_headers, made):
    user, headers = _user(client, auth_headers, made)
    r = client.put(ME, headers=headers, json={"display_name": "  测试员  ", "email": "t@example.com", "phone": "13812345678"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["display_name"], body["email"], body["phone_masked"]) == ("测试员", "t@example.com", "138****5678")
    assert "13812345678" not in r.text and "phone" not in body  # 完整手机号不出现在任何响应里
    r = client.put(ME, headers=headers, json={"email": None})  # 只清邮箱，其余不动
    assert (r.json()["display_name"], r.json()["email"], r.json()["phone_masked"]) == ("测试员", None, "138****5678")
    assert client.get(ME, headers=headers).json()["phone_masked"] == "138****5678"
    db = SessionLocal()
    try:
        audits = db.query(AuditLog).filter(AuditLog.resource == "user", AuditLog.resource_id == user["id"], AuditLog.action == "update").all()
        assert [a.detail["changed"] for a in audits] == [["display_name", "email", "phone"], ["email"]]
        assert all("13812345678" not in str(a.detail) and "t@example.com" not in str(a.detail) for a in audits)
    finally:
        db.close()


@pytest.mark.parametrize("body", [{"email": "not-an-email"}, {"phone": "abc123"}, {"phone": "1" * 21}, {"display_name": "名" * 65},
                                  {"role": "admin"}, {"username": "rename"}])
def test_profile_update_rejects_bad_values_and_privileged_fields(client, auth_headers, made, body):
    """格式不对、超长 422；角色与用户名不能自己改（未知字段 422，不悄悄忽略）。"""
    _, headers = _user(client, auth_headers, made)
    assert client.put(ME, headers=headers, json=body).status_code == 422


def test_profile_endpoints_reject_api_key(client, auth_headers, made, key_scope):
    """个人中心的写操作与"我的 API 密钥"只认 JWT：拿着 Key 的外部系统不能改归属人资料、踢掉归属人登录、列出其他 Key。"""
    key = _key(client, auth_headers, made, key_scope).json()
    bearer = {"Authorization": "Bearer " + key["key"]}
    for method, path in (("put", ME), ("post", ME + "/logout-others"), ("get", ME + "/logins"), ("get", ME + "/api-keys")):
        r = getattr(client, method)(path, headers=bearer, **({"json": {}} if method == "put" else {}))
        assert r.status_code == 403 and r.json()["detail"].startswith("API Key 不能"), (path, r.text)


# ---------- 退出其他设备与登录记录 ----------

def test_logout_others_revokes_old_tokens_and_returns_a_new_one(client, auth_headers, made):
    user, other_device = _user(client, auth_headers, made)
    this_device = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"username": user["username"], "password": PASSWORD}).json()["token"]}
    r = client.post(ME + "/logout-others", headers=this_device)
    assert r.status_code == 200, r.text
    fresh = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.get(ME, headers=other_device).status_code == 401
    assert client.get(ME, headers=this_device).status_code == 401  # 发起请求的旧令牌同样作废，页面要换上新令牌
    assert client.get(ME, headers=fresh).status_code == 200


def test_login_history_lists_own_successes_and_failures_newest_first(client, auth_headers, made):
    user, headers = _user(client, auth_headers, made)
    assert client.post("/api/v1/auth/login", json={"username": user["username"], "password": "wrong-password"}).status_code == 401
    client.post("/api/v1/auth/login", json={"username": user["username"], "password": PASSWORD})
    other, _ = _user(client, auth_headers, made)  # 别人的登录不出现
    rows = client.get(ME + "/logins", headers=headers).json()
    assert [r["success"] for r in rows] == [True, False, True]  # 最新的在前：再次登录、输错一次、_user 里的首次登录
    assert all(set(r) == {"created_at", "ip", "success"} for r in rows)
    assert other["username"] not in client.get(ME + "/logins", headers=headers).text


# ---------- 我的 API 密钥与代发（D-15） ----------

def test_admin_issues_key_to_caller_who_sees_it_read_only(client, auth_headers, made, key_scope):
    caller, caller_headers = _user(client, auth_headers, made)
    r = _key(client, auth_headers, made, key_scope, owner_user_id=caller["id"])
    assert r.status_code == 200, r.text
    assert (r.json()["user_id"], r.json()["username"]) == (caller["id"], caller["username"])
    mine = client.get(ME + "/api-keys", headers=caller_headers)
    assert mine.status_code == 200 and [k["id"] for k in mine.json()["items"]] == [r.json()["id"]]
    assert r.json()["key"] not in mine.text and "key_hash" not in mine.text
    assert client.post(f"{KEYS}/{r.json()['id']}/toggle", headers=caller_headers).status_code == 403  # 调用者只读，要停用找管理员
    db = SessionLocal()
    try:
        audit = db.query(AuditLog).filter(AuditLog.action == "create", AuditLog.resource == "api_key", AuditLog.resource_id == r.json()["id"]).one()
        assert audit.detail["owner_user_id"] == caller["id"] and r.json()["key"] not in str(audit.detail)
    finally:
        db.close()


def test_only_admin_can_issue_keys_to_active_users(client, auth_headers, made, key_scope):
    caller, _ = _user(client, auth_headers, made)
    _, dev_headers = _user(client, auth_headers, made, "developer")
    r = _key(client, dev_headers, made, key_scope, owner_user_id=caller["id"])
    assert r.status_code == 403 and r.json()["detail"] == "只有管理员能替其他用户生成 API Key"
    assert _key(client, auth_headers, made, key_scope, owner_user_id=999999991).status_code == 400
    assert client.put(f"/api/v1/users/{caller['id']}", headers=auth_headers, json={"is_active": False}).status_code == 200
    r = _key(client, auth_headers, made, key_scope, owner_user_id=caller["id"])
    assert r.status_code == 400 and r.json()["detail"] == "归属用户不存在或已停用"


def test_my_api_keys_only_lists_own_keys(client, auth_headers, made, key_scope):
    """developer 在"我的 API 密钥"只看到自己的 Key（admin 的不出现），AC-033 ⑤。"""
    _, dev_headers = _user(client, auth_headers, made, "developer")
    mine = _key(client, dev_headers, made, key_scope).json()
    _key(client, auth_headers, made, key_scope)
    assert [k["id"] for k in client.get(ME + "/api-keys", headers=dev_headers).json()["items"]] == [mine["id"]]
