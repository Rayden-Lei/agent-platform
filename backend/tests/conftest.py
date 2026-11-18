import os
import time
import uuid
from pathlib import Path

from dotenv import dotenv_values

# 测试默认关闭入口限流：整套用例串行打同一个 admin 用户，开着会撞上用户维度的上限。
# 必须在 import app 之前设置（settings 在 app.config 导入时实例化）；限流用例自己用 monkeypatch 打开。
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# 测试进程关闭调度器选主：开发库是共享的，本机跑着的后端会持有 PostgreSQL advisory lock，
# 不关的话 pytest 进程就成了"非主实例"、一条 cron 都不注册 —— 用例结果取决于别人有没有开服务，不可复现。
# 关掉等于"本进程必为主"，与 2026-11-18 之前的单实例行为一致；选主本身由 test_scheduler_reliability.py 显式打开验证。
os.environ.setdefault("SCHEDULER_LEADER_ELECTION_ENABLED", "false")
# 测试进程绝不做"启动自动续处理"：开发库是共享的，同一台机器上的后端可能正在导入真实文档，
# 测试里的解析/向量化又全是打桩，抢过来会按假数据重建切片（2026-09-06 删掉过用户 1.9 万片真实切片）。
os.environ.setdefault("INGEST_AUTO_RESUME", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests import cleanup  # noqa: E402

# 测试会话互斥锁（PostgreSQL advisory lock）的键：与调度器选主的键刻意不同。
# 见 _acquire_session_lock：共享开发库上并发跑 pytest 会互相删数据，必须串行。
TEST_SESSION_LOCK_KEY = 0x5054455354534553  # b"PTESTSE S"
# 抢不到锁时最多排队等这么久（秒）：并行跑是常态，先等，等不到才退出。
# 取 10 分钟是因为单文件测试常有 1～2 分钟，等一轮完整会话结束要留够余量。
SESSION_LOCK_WAIT_SECONDS = 600
_session_lock_conn = None


def _acquire_session_lock() -> bool:
    """抢「同一时刻只允许一个 pytest 会话」的锁，抢不到返回 False。

    为什么必须有这把锁（2026-11-18）：开发库只有一套、且是共享的，而清理逻辑
    （tests/cleanup.py）按 pytest- 前缀 + 时间窗回收，无法区分「我造的行」与「另一个会话造的行」。
    两个会话并发跑时，A 的 sessionfinish 会把 B 正在用的夹具删掉，B 随后撞
    ForeignKeyViolation（conversations_agent_id_fkey / agents_model_id_fkey / runs_schedule_id_fkey），
    单独跑每条都通过、合起来跑就红 —— 排查方向会被彻底带偏到业务代码上。

    试过但不够的两个办法（记下来避免以后重走）：
    1. 给前置回收加宽限期（CLEANUP_GRACE_MINUTES）：只解决「会话刚启动就删别人刚建的行」，
       挡不住「先结束的会话删后结束会话的行」；
    2. 只靠约定「不要并行跑」：约定挡不住并发（多个 agent / 多个终端 / CI 与本机）。

    所以用数据库层的连接级 advisory lock 真正串行化：抢到锁才跑，抢不到就以退出码 3 结束并说明原因。
    锁跟着连接走，进程被杀由服务端自动释放，不会留下「锁被永久占住、谁都跑不了」的死局。
    """
    global _session_lock_conn
    from psycopg import OperationalError, connect

    from app.config import settings
    from app.workflow.checkpointer import libpq_dsn

    try:
        conn = connect(libpq_dsn(settings.DATABASE_URL), autocommit=True, connect_timeout=30)
    except OperationalError as e:
        # 连不上库时不做互斥判断：让后续用例自己去撞连接错误，报错更具体
        print(f"\n[互斥锁] 连不上数据库，跳过会话互斥判断：{e}")
        return True
    # 先**排队等**而不是立刻失败：并行 agent / 多终端同时跑是常态，
    # 等一会儿让它们自动串行，比直接报"另一个会话在跑"体验好得多。
    # 等满 SESSION_LOCK_WAIT_SECONDS 仍拿不到才退出 —— 那说明真有一个长会话在跑，
    # 这时候报错比让两轮一起跑出满屏假失败要好。
    deadline = time.monotonic() + SESSION_LOCK_WAIT_SECONDS
    waited = False
    while True:
        row = conn.execute("SELECT pg_try_advisory_lock(%s)", (TEST_SESSION_LOCK_KEY,)).fetchone()
        if row is not None and row[0]:
            _session_lock_conn = conn
            if waited:
                print(f"\n[互斥锁] 已等到前一个 pytest 会话结束，本会话开始")
            return True
        if time.monotonic() >= deadline:
            break
        if not waited:
            print(f"\n[互斥锁] 另一个 pytest 会话正在使用开发库，最多等 {SESSION_LOCK_WAIT_SECONDS} 秒…")
            waited = True
        time.sleep(2)
    conn.close()
    return False


def pytest_sessionstart(session):  # noqa: ARG001
    """记下会话开始时间：结束时只回收这之后造的数据，不碰别人之前留下的行。

    开跑前先做两件事：抢会话互斥锁（见 _acquire_session_lock），再清一次历史残留。

    为什么抢锁：共享开发库上并发跑 pytest 会互相删夹具，产生大量与业务代码无关的假失败。
    抢不到锁时以退出码 3 结束 —— 明确告诉调用方「另一个会话在跑，请等它结束」，
    而不是让两轮测试一起跑出满屏 ForeignKeyViolation。

    为什么还要清历史残留：sessionfinish 只有在会话正常结束时才执行，
    进程被 kill（Ctrl-C、OOM、超时）时完全不跑，上一轮的行就永久留在库里，
    而且下一轮的 sessionfinish 只覆盖自己的时间窗，清不到它 —— 越积越多。
    2026-11-15 就是这么漏出 2 个 pytest-share-kb-* 知识库 + 17 个 pytest-embed-* 模型 +
    110 个 11-08 的 pytest-mcp-bulk-* 工具，知识库列表页直接把它们显示给了使用者。

    判据仍是 pytest- 前缀，真实数据碰不到；被真实数据以 RESTRICT 引用的行会跳过。
    失败只报告不拦测试 —— 前置清理是收尾性质，不该让整轮跑不起来。
    """
    if not _acquire_session_lock():
        pytest.exit(
            "另一个 pytest 会话正在使用这个开发库（共享库上的测试互斥锁被占用）。\n"
             "并发跑会互相删除夹具数据、产生与代码无关的假失败，所以这里直接退出。\n"
            "等前一个会话结束后重跑；确认没有别的会话在跑时，可查 pg_locks 里 objid = " + str(TEST_SESSION_LOCK_KEY) + " 的 advisory lock。",
            returncode=3,
        )
    session.config._test_started_at = cleanup.session_start()
    try:
        # 只清宽限期之前的残留（默认 30 分钟）：开发库是共享的，并行跑测试时后启动的会话
        # 不能把先启动会话正在用的夹具删掉（2026-11-18 之前判据是"全部历史"，会踩这个坑）
        stale = cleanup.purge_all_history()
        if stale:
            detail = "、".join(f"{t} {n}" for t, n in stale.items())
            print(f"\n[清理] 开跑前回收历史残留（{cleanup.CLEANUP_GRACE_MINUTES} 分钟前）：{detail}")
    except cleanup.CleanupAborted as exc:
        print(f"\n[清理跳过] 历史残留回收被中止：{exc}")
    except Exception as exc:  # noqa: BLE001 前置清理失败不拦测试
        print(f"\n[清理失败] 历史残留回收：{type(exc).__name__}: {exc}")

    # 建表失败不能拦死整轮：绝大多数用例不碰工作流，它们没有理由因为 checkpoint 表建不上而全红。
    # 真正需要这张表的用例会在第一次写检查点时拿到明确的 UndefinedTable/连接错误。
    try:
        _ensure_checkpoint_schema()
    except Exception:  # noqa: BLE001 会话初始化是前置动作，失败只报告
        import logging

        logging.getLogger(__name__).exception("checkpoint 表初始化失败，跑图的用例可能失败")


def _ensure_checkpoint_schema() -> None:
    """确保 checkpoint 表存在（工作流 checkpointer 换成 Postgres 之后，图一跑就要写这几张表）。

    为什么在测试里建、而不是让应用启动时建：生产不在启动路径做 DDL（表由
    backend/scripts/migrations 下的迁移脚本负责）。但 CI 是空库，_init_db 里的
    Base.metadata.create_all 只建 ORM 表，建不到 saver 自己的 4 张表 —— 不在这里补，
    CI 上所有跑图的用例都会 UndefinedTable。用同一个幂等入口 checkpointer.apply_migrations，
    与迁移脚本不产生第二份 DDL。
    """
    from psycopg import connect
    from psycopg.rows import dict_row

    from app.config import settings
    from app.workflow.checkpointer import apply_migrations, libpq_dsn

    # 连接超时给足 30 秒：本机经 SSH 隧道连云端库时，往返延迟的**尾**很难看。
    # 2026-11-18 实测（50 次采样，单条 SSH 会话内）：p50 28ms、p90 74ms、p99 619ms、max 619ms，
    # 而服务器直连同一套库是 p50 0.2ms。用 10 秒这种紧值会让"隧道喘一下"
    # 直接升级成 INTERNALERROR —— 收集阶段硬失败时整轮测试都跑不起来，排查方向还会被带偏到代码上。
    # （这也解释了为什么全量测试要在服务器上跑：本地每次查询多付 25ms，1185 条用例累积成 27 分钟。）
    with connect(libpq_dsn(settings.DATABASE_URL), autocommit=True, row_factory=dict_row, connect_timeout=30) as conn:
        conn.execute("SET lock_timeout = '5s'")
        apply_migrations(conn)


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """兜底回收 pytest- 前缀的残留。

    用例自己写 finally 清理是主路径，但进程被 kill、解释器崩溃、finally 里自己抛错时都会漏。
    这里在会话结束统一扫一遍；清理失败只报告，不改退出码——它不该把一次正常的测试跑成失败。
    最后释放会话互斥锁：不释放的话下一个会话要等到这条连接被服务端判死才能开始。
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
    # checkpointer 的连接池是进程级资源：直接编译图的用例不走 lifespan，是懒打开的，
    # 会话结束统一关掉，别把连接留在共享开发库上（与 lifespan 的关闭语义一致）
    from app.workflow import checkpointer
    checkpointer.close_checkpointer()
    _release_session_lock()


def _release_session_lock() -> None:
    """释放会话互斥锁（关闭连接即可；advisory lock 跟着连接走）。

    放在 sessionfinish 的最后：清理还在用库，锁要一直持有到清理结束。
    """
    global _session_lock_conn
    conn = _session_lock_conn
    _session_lock_conn = None
    if conn is None:
        return
    try:
        conn.execute("SELECT pg_advisory_unlock(%s)", (TEST_SESSION_LOCK_KEY,))
    except Exception:  # noqa: BLE001 连接可能已断，锁也随之释放
        pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


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
def embedding_model(client, auth_headers) -> dict:
    """给知识库测试用的向量模型：建库必须绑一个真实存在且启用的模型（2026-11-08 起的契约）。

    **function 级**，理由同 key_scope：tests/test_cleanup.py 会按 pytest- 前缀整表回收，
    session 级的行会被它删掉，后续用例再引用就 404，且失败按执行顺序漂移、极难排查。

    dim 必须与切片表列宽一致（服务端会校验，不一致直接 422）。地址指向不可达域名：
    这些用例的入库全被打桩，不走真实向量服务。
    """
    from app.config import settings

    r = client.post("/api/v1/embedding-models", headers=auth_headers, json={
        "name": "pytest-embedding-model", "provider": "openai", "api_base": "https://pytest.invalid/v1",
        "api_key": "pytest-key", "model_name": "pytest-embed-model",
        "dim": settings.EMBEDDING_DIM, "request_size": 20, "is_enabled": True,
    })
    assert r.status_code == 200, r.text
    row = r.json()
    try:
        yield row
    finally:
        client.delete(f"/api/v1/embedding-models/{row['id']}", headers=auth_headers)


def publish_workflow(client, headers, workflow_id: int) -> dict:
    """把工作流发布成线上版本（FR-075）。

    2026-11-15 起工作流是"保存草稿 → 发布上线"两段：run / 对话 / 定时任务 / API Key 一律读线上版本，
    未发布一律 403。因此凡是要真的跑一次工作流的用例，建完工作流必须先发布 —— 这一行就是那个前提，
    抽成函数是为了让用例里"为什么多这一步"有地方写清楚，不要各文件各写一遍。
    """
    r = client.post(f"/api/v1/workflows/{workflow_id}/publish", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def client_from(client):
    """以指定对端地址建 TestClient，模拟不同来源 IP。依赖 client 是为了保证 lifespan 已经跑过（建表、管理员）。"""

    def _make(ip: str) -> TestClient:
        return TestClient(app, client=(ip, 50000))

    return _make
