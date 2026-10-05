"""账号安全（docs/15 OP-04，AC-033 ①～④）：用户入参校验、令牌版本吊销、必须改密的服务端强制、本人改密、停用账号的定时任务。

只操作本用例建的 pytest- 用户；共享库里的 admin 不会被改动（必须改密、重置都只对测试用户做）。
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import settings
from app.core import scheduler
from app.core.security import ALGORITHM, verify_password
from app.db.models import Run, User
from app.db.session import SessionLocal
from app.services import user_service

MUST_CHANGE = "请先修改初始密码"


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def account(client, auth_headers):
    """一个临时 developer 账号：返回 {id, username, password}，用例结束删除（先删它名下的工作流）。"""
    username, password = "pytest-acct-" + _uid(), "first-pass-1"
    created = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": password, "role": "developer"})
    assert created.status_code == 200, created.text
    info = {"id": created.json()["id"], "username": username, "password": password, "workflows": []}
    yield info
    for wid in info["workflows"]:
        client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)
    client.delete(f"/api/v1/users/{info['id']}", headers=auth_headers)


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _user_count(username: str) -> int:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == username.strip()).count()
    finally:
        db.close()


@pytest.mark.parametrize("body", [
    {"username": "pytest-bad-role-{uid}", "password": "pass-123", "role": "superadmin"},
    {"username": "pytest-empty-pw-{uid}", "password": "", "role": "caller"},
    {"username": "pytest-short-pw-{uid}", "password": "12345", "role": "caller"},
    {"username": "p" * 65, "password": "pass-123", "role": "caller"},
    {"username": "pytest has-space-{uid}", "password": "pass-123", "role": "caller"},
    {"username": " x ", "password": "pass-123", "role": "caller"},
])
def test_invalid_user_payloads_are_422_and_create_nothing(client, auth_headers, body):
    body = {**body, "username": body["username"].format(uid=_uid())}
    r = client.post("/api/v1/users", headers=auth_headers, json=body)
    if r.status_code == 200:  # 修复前会落库：先删掉再让断言失败
        client.delete(f"/api/v1/users/{r.json()['id']}", headers=auth_headers)
    assert r.status_code == 422 and _user_count(body["username"]) == 0


def test_reset_password_revokes_existing_sessions(client, auth_headers, account):
    old = _login(client, account["username"], account["password"])
    assert client.get("/api/v1/auth/me", headers=old).status_code == 200
    r = client.post(f"/api/v1/users/{account['id']}/reset-password", headers=auth_headers, json={"password": "reset-pass-1", "must_change_password": False})
    assert r.status_code == 200
    stale = client.get("/api/v1/auth/me", headers=old)
    assert stale.status_code == 401 and stale.json()["detail"] == "登录已失效，请重新登录"
    assert client.get("/api/v1/agents", headers=_login(client, account["username"], "reset-pass-1")).status_code == 200


def test_must_change_password_is_enforced_until_changed(client, auth_headers, account):
    client.post(f"/api/v1/users/{account['id']}/reset-password", headers=auth_headers, json={"password": "temp-pass-1"})  # 默认要求改密
    login = client.post("/api/v1/auth/login", json={"username": account["username"], "password": "temp-pass-1"}).json()
    assert login["user"]["must_change_password"] is True
    headers = {"Authorization": "Bearer " + login["token"]}
    blocked = client.get("/api/v1/agents", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["detail"] == MUST_CHANGE
    assert client.get("/api/v1/auth/me", headers=headers).json()["must_change_password"] is True
    change = lambda old, new: client.put("/api/v1/auth/me/password", headers=headers, json={"old_password": old, "new_password": new})  # noqa: E731
    assert change("wrong-pass", "final-pass-1").status_code == 400
    assert change("temp-pass-1", "temp-pass-1").status_code == 400
    assert change("temp-pass-1", "12345").status_code == 422
    done = change("temp-pass-1", "final-pass-1")
    assert done.status_code == 200 and done.json()["user"]["must_change_password"] is False
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401  # 改密后旧令牌作废
    fresh = {"Authorization": "Bearer " + done.json()["token"]}
    assert client.get("/api/v1/agents", headers=fresh).status_code == 200


def test_api_key_cannot_change_password(client, auth_headers, key_scope):
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-acct-key", "quota": 10, **key_scope}).json()
    try:
        r = client.put("/api/v1/auth/me/password", headers={"Authorization": "Bearer " + key["key"]}, json={"old_password": "x", "new_password": "whatever-1"})
        assert r.status_code == 403
    finally:
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)


def test_disabling_a_user_revokes_its_tokens_even_after_reenabling(client, auth_headers, account):
    old = _login(client, account["username"], account["password"])
    client.put(f"/api/v1/users/{account['id']}", headers=auth_headers, json={"is_active": False})
    # 2026-10-05 起停用账号的登录令牌是 401（OP-02）：前端只在 401 清登录态回登录页，此前 403 时页面停在原处一直报错
    disabled = client.get("/api/v1/auth/me", headers=old)
    assert disabled.status_code == 401 and disabled.json()["detail"] == "账号已停用或不存在，请重新登录"
    client.put(f"/api/v1/users/{account['id']}", headers=auth_headers, json={"is_active": True})
    assert client.get("/api/v1/auth/me", headers=old).status_code == 401  # 重新启用也不复活停用前的会话


def test_tokens_issued_before_versioning_still_work(client, account):
    """OP-04 之前签发的令牌没有 ver：所有人当时的版本都是 0，按 0 比对，部署时不会把所有人踢下线。"""
    legacy = jwt.encode({"sub": str(account["id"]), "role": "developer", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, settings.SECRET_KEY, algorithm=ALGORITHM)
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + legacy}).status_code == 200


def test_disabled_creators_schedule_leaves_a_failed_run_instead_of_running(client, auth_headers, account):
    dev = _login(client, account["username"], account["password"])
    graph = {"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "e", "type": "end", "config": {}}], "edges": [{"from": "s", "to": "e"}]}
    wf = client.post("/api/v1/workflows", headers=dev, json={"name": "pytest-acct-wf-" + _uid(), "description": "", "graph": graph}).json()
    account["workflows"].append(wf["id"])
    job = client.post("/api/v1/schedules", headers=dev, json={"name": "pytest-acct-job-" + _uid(), "workflow_id": wf["id"], "cron": "0 3 1 1 *"}).json()
    try:
        client.put(f"/api/v1/users/{account['id']}", headers=auth_headers, json={"is_active": False})
        scheduler._run_scheduled_job(job["id"], force=True)
        db = SessionLocal()
        try:
            runs = db.query(Run).filter(Run.schedule_id == job["id"]).all()
            assert [(r.status, r.error) for r in runs] == [("failed", "创建人已停用，任务未执行")]
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/schedules/{job['id']}", headers=auth_headers)


class _NoAdminDb:
    """只给 ensure_initial_admin 用的假会话：库里没有 admin，记下新建的用户。共享库里的 admin 一行不动。"""

    def __init__(self):
        self.added = []

    def query(self, *args):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass


@pytest.mark.parametrize("configured", ["init-pass-123", ""])
def test_initial_admin_uses_configured_password_or_forces_a_change(monkeypatch, configured):
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", configured)
    db = _NoAdminDb()
    assert user_service.ensure_initial_admin(db) == ("configured" if configured else "default")
    admin = db.added[0]
    assert verify_password(configured or user_service.DEFAULT_ADMIN_PASSWORD, admin.password_hash)
    assert admin.must_change_password is (not configured)
