import os

# 测试默认关闭入口限流：整套用例串行打同一个 admin 用户，开着会撞上用户维度的上限。
# 必须在 import app 之前设置（settings 在 app.config 导入时实例化）；限流用例自己用 monkeypatch 打开。
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# 测试进程绝不做"启动自动续处理"：开发库是共享的，同一台机器上的后端可能正在导入真实文档，
# 测试里的解析/向量化又全是打桩，抢过来会按假数据重建切片（2026-09-06 删掉过用户 1.9 万片真实切片）。
os.environ.setdefault("INGEST_AUTO_RESUME", "false")

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
