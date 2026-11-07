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
from tests import cleanup  # noqa: E402


def pytest_sessionstart(session):  # noqa: ARG001
    """记下会话开始时间：结束时只回收这之后造的数据，不碰别人之前留下的行。"""
    session.config._test_started_at = cleanup.session_start()


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """兜底回收 pytest- 前缀的残留。

    用例自己写 finally 清理是主路径，但进程被 kill、解释器崩溃、finally 里自己抛错时都会漏。
    这里在会话结束统一扫一遍；清理失败只报告，不改退出码——它不该把一次正常的测试跑成失败。
    """
    started = getattr(session.config, "_test_started_at", None)
    if started is None:
        return
    try:
        deleted = cleanup.purge_since(started)
    except cleanup.CleanupAborted as exc:
        print(f"\n[清理跳过] {exc}")
        return
    except Exception as exc:  # noqa: BLE001 清理是收尾动作，不能因此让测试失败
        print(f"\n[清理失败] {type(exc).__name__}: {exc}")
        return
    if deleted:
        detail = "、".join(f"{t} {n}" for t, n in deleted.items())
        print(f"\n[清理] 回收测试残留：{detail}")


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
    # 跟随 ENV_FILE（与 app/config.py 同口径）：同一份代码跑多套环境时，口令要取正在用的那份配置，
    # 否则会拿 .env 里的口令去登 .env.local 建的库。
    env_file = Path(__file__).resolve().parents[1] / os.environ.get("ENV_FILE", ".env")
    password = os.environ.get("TEST_ADMIN_PASSWORD") or dotenv_values(env_file).get("TEST_ADMIN_PASSWORD")
    if not password:
        pytest.exit(f"未配置 TEST_ADMIN_PASSWORD：本地写在 {env_file.name}，CI 在 .github/workflows/ci.yml 设置", returncode=2)
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


@pytest.fixture
def key_scope(client, auth_headers) -> dict:
    """建 API Key 必须带至少一项作用域（docs/15 3.7.1，2026-10-05 起）。不关心作用域的用例（鉴权、配额、限流、管理接口拒绝）
    共用这个只授权了一个空流程工作流的作用域；真要调智能体或工作流的用例按实际调用的资源授权。

    **必须是 function 级，不能是 session 级**（2026-11-07 改）。原来是 session 级，只在会话开头
    建一次，然后全会话复用 —— 但 tests/test_cleanup.py 会调 cleanup.purge_test_rows()，
    按 `pytest-` 前缀 + 时间窗整表回收，这个工作流名字正好是 `pytest-key-scope-*`，
    于是被当成残留删掉，后续所有用它的用例拿到「工作流不存在」再 KeyError。
    症状极具迷惑性：单跑某个文件时好时坏、换个顺序就换一批用例失败。

    function 级的代价是每个用例多建删一个工作流（轻量操作），换来的是彻底没有顺序依赖。
    """
    graph = {"nodes": [{"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}}, {"id": "e", "type": "end", "config": {}}], "edges": [{"from": "s", "to": "e"}]}
    w = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-key-scope-" + uuid.uuid4().hex[:6], "description": "", "graph": graph})
    assert w.status_code == 200, w.text
    try:
        yield {"workflow_ids": [w.json()["id"]]}
    finally:
        client.delete(f"/api/v1/workflows/{w.json()['id']}", headers=auth_headers)


@pytest.fixture
def client_from(client):
    """以指定对端地址建 TestClient，模拟不同来源 IP。依赖 client 是为了保证 lifespan 已经跑过（建表、管理员）。"""

    def _make(ip: str) -> TestClient:
        return TestClient(app, client=(ip, 50000))

    return _make
