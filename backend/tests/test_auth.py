def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_login_success(client):
    res = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    assert "token" in res.json()


def test_login_wrong_password(client):
    res = client.post("/api/v1/auth/login", json={"username": "no_such_user_xyz", "password": "wrong"})
    assert res.status_code == 401


def test_me(client, auth_headers):
    res = client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["username"] == "admin"


def test_unauthorized(client):
    res = client.get("/api/v1/models")
    assert res.status_code == 401
