import uuid


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_login_success(client, admin_login):
    res = client.post("/api/v1/auth/login", json=admin_login)
    assert res.status_code == 200
    assert "token" in res.json()


def test_login_wrong_password(client):
    """口令错误应 401。

    **用户名必须每次唯一**：失败计数存在 Redis 的 login_fail:{username}，窗口 10 分钟，
    达到阈值后返回 429 而不是 401。固定用户名会让这个用例在 10 分钟内跑第 6 次时失败，
    而它的断言完全正确 —— 是测试之间没有隔离（2026-11-15 三次全量里两次踩到，
    每次报错都是 assert 429 == 401，看起来像认证缺陷，实际是残留计数）。
    """
    username = "no_such_user_" + uuid.uuid4().hex[:12]
    res = client.post("/api/v1/auth/login", json={"username": username, "password": "wrong"})
    assert res.status_code == 401


def test_me(client, auth_headers):
    res = client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["username"] == "admin"


def test_unauthorized(client):
    res = client.get("/api/v1/models")
    assert res.status_code == 401
