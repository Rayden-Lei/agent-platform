import os

# 测试默认关闭入口限流：整套用例串行打同一个 admin 用户，开着会撞上用户维度的上限。
# 必须在 import app 之前设置（settings 在 app.config 导入时实例化）；限流用例自己用 monkeypatch 打开。
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_headers(client):
    res = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200, res.text
    token = res.json()["token"]
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def client_from(client):
    """以指定对端地址建 TestClient，模拟不同来源 IP。依赖 client 是为了保证 lifespan 已经跑过（建表、管理员）。"""

    def _make(ip: str) -> TestClient:
        return TestClient(app, client=(ip, 50000))

    return _make
