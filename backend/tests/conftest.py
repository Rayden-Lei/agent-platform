import os
from pathlib import Path

from dotenv import dotenv_values

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
def admin_login() -> dict:
    """管理员登录体。口令读环境变量 TEST_ADMIN_PASSWORD，没有再读 backend/.env（app 的 settings 读的也是这个文件）。

    口令不写进代码：开发库是共享的、服务器对公网开放，写死在仓库里的默认口令等于公开口令（2026-09-25 改掉）。
    CI 是空库，应用启动时建的 admin 用默认口令，在 ci.yml 里显式设置。
    """
    password = os.environ.get("TEST_ADMIN_PASSWORD") or dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("TEST_ADMIN_PASSWORD")
    if not password:
        pytest.exit("未配置 TEST_ADMIN_PASSWORD：本地写在 backend/.env，CI 在 .github/workflows/ci.yml 设置", returncode=2)
    return {"username": "admin", "password": password}


@pytest.fixture(scope="session")
def auth_headers(client, admin_login):
    res = client.post("/api/v1/auth/login", json=admin_login)
    assert res.status_code == 200, res.text
    token = res.json()["token"]
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def client_from(client):
    """以指定对端地址建 TestClient，模拟不同来源 IP。依赖 client 是为了保证 lifespan 已经跑过（建表、管理员）。"""

    def _make(ip: str) -> TestClient:
        return TestClient(app, client=(ip, 50000))

    return _make
