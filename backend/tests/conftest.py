import os
import uuid
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
def caller_headers(client, auth_headers):
    """临时 caller 账号的登录头（用例结束删掉账号）。验证"调用者被拒"类负向用例用。"""
    username = "pytest-caller-" + uuid.uuid4().hex[:6]
    created = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "caller123", "role": "caller"})
    assert created.status_code == 200, created.text
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "caller123"}).json()["token"]
    yield {"Authorization": "Bearer " + token}
    client.delete(f"/api/v1/users/{created.json()['id']}", headers=auth_headers)


@pytest.fixture(scope="session")
def key_scope(client, auth_headers) -> dict:
    """建 API Key 必须带至少一项作用域（docs/15 3.7.1，2026-10-05 起）。不关心作用域的用例（鉴权、配额、限流、管理接口拒绝）
    共用这个只授权了一个空流程工作流的作用域；真要调智能体或工作流的用例按实际调用的资源授权。"""
    graph = {"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "e", "type": "end", "config": {}}], "edges": [{"from": "s", "to": "e"}]}
    w = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-key-scope-" + uuid.uuid4().hex[:6], "description": "", "graph": graph})
    assert w.status_code == 200, w.text
    yield {"workflow_ids": [w.json()["id"]]}
    client.delete(f"/api/v1/workflows/{w.json()['id']}", headers=auth_headers)


@pytest.fixture
def client_from(client):
    """以指定对端地址建 TestClient，模拟不同来源 IP。依赖 client 是为了保证 lifespan 已经跑过（建表、管理员）。"""

    def _make(ip: str) -> TestClient:
        return TestClient(app, client=(ip, 50000))

    return _make
