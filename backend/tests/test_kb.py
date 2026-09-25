def test_kb_crud(client, auth_headers):
    k = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": "pytest-kb", "description": "", "embedding_model": "embedding-3", "chunk_size": 200, "chunk_overlap": 20,
    })
    assert k.status_code == 200, k.text
    kid = k.json()["id"]

    l = client.get("/api/v1/knowledge-bases", headers=auth_headers)
    assert l.status_code == 200
    assert any(x["id"] == kid for x in l.json()["items"])

    d = client.delete(f"/api/v1/knowledge-bases/{kid}", headers=auth_headers)
    assert d.status_code == 200


def test_upload_does_not_block_event_loop(monkeypatch, client, auth_headers):
    """上传大文件期间事件循环必须保持可用。

    2026-09-06 的真实故障：上传路由是 async def 却在里面直接做阻塞的 MinIO 上传，
    一次上传重试到 436 秒，期间整个后端不处理任何请求，页面看着像服务挂了。

    判据是**并发协程被唤醒的时刻**：让一个协程睡 0.3 秒后记时间。
    循环没被占住时它准点醒（约 0.3 秒）；阻塞 IO 跑在循环上时，它要等阻塞结束才醒（实测 2.4 秒）。
    不能用"谁先返回"当判据 —— 阻塞版里健康检查醒来后反而先于上传返回，那样测不出问题（试过）。
    """
    import asyncio
    import time

    import httpx

    from app.api.v1 import kb as kb_router
    from app.main import app
    from app.services import kb_service

    kb_id = client.post("/api/v1/knowledge-bases", headers=auth_headers,
                        json={"name": "pytest-upload-block-kb", "chunk_size": 200, "chunk_overlap": 0}).json()["id"]
    monkeypatch.setattr(kb_service, "upload_file", lambda name, data, ctype: time.sleep(1.5))  # 阻塞 IO 替身
    monkeypatch.setattr(kb_router, "process_document", lambda doc_id, resume=False: None)  # 不真的入库

    async def _scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            started = time.perf_counter()

            async def _upload():
                return await ac.post(f"/api/v1/knowledge-bases/{kb_id}/documents", headers=auth_headers,
                                     files={"file": ("pytest-slow.txt", b"x" * 1024, "text/plain")}, timeout=30)

            async def _health():
                await asyncio.sleep(0.3)  # 上传此时已进入阻塞段
                woke = time.perf_counter() - started
                return await ac.get("/health", timeout=10), woke

            uploaded, (health, woke) = await asyncio.gather(_upload(), _health())
            return uploaded, health, woke

    try:
        uploaded, health, woke = asyncio.run(_scenario())
        assert uploaded.status_code == 200, uploaded.text
        assert health.status_code == 200
        assert woke < 1.0, f"并发协程被饿了 {woke:.2f} 秒才唤醒：阻塞 IO 跑在了事件循环上"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)


# ---------- 知识库改权限立即生效：检索鉴权读知识库当前权限，不读切片里入库时的快照（2026-09-25） ----------

import uuid  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models import Document, DocumentChunk  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.rag import retriever  # noqa: E402

ACL_CONTENT = "智枢请假流程：员工提交申请后由直属主管审批"
ACL_QUERY = "请假流程"


@pytest.fixture
def developer_headers(client, auth_headers):
    username = "pytest-kb-dev-" + uuid.uuid4().hex[:6]
    created = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "dev12345", "role": "developer"})
    assert created.status_code == 200, created.text
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "dev12345"}).json()["token"]
    yield {"Authorization": "Bearer " + token}
    client.delete(f"/api/v1/users/{created.json()['id']}", headers=auth_headers)


@pytest.fixture
def offline_retrieval(monkeypatch):
    """检索不连外部模型：查询向量打桩，重排走词法（本机 .env 可能指向没在跑的 oMLX）。"""
    monkeypatch.setattr(retriever, "embed_query", lambda text: [0.1] * settings.EMBEDDING_DIM)
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "")


def _kb_with_one_chunk(client, auth_headers, *, is_public: bool, visible_roles: list) -> dict:
    """建库并直接插一条切片（不走 MinIO 与解析）；切片 meta 按入库时的权限写快照，与 pipeline 的写法一致。"""
    body = {"name": "pytest-kb-acl-" + uuid.uuid4().hex[:6], "chunk_size": 200, "chunk_overlap": 0, "is_public": is_public, "visible_roles": visible_roles}
    created = client.post("/api/v1/knowledge-bases", headers=auth_headers, json=body)
    assert created.status_code == 200, created.text
    db = SessionLocal()
    try:
        doc = Document(kb_id=created.json()["id"], name="pytest-acl.txt", file_path="pytest/unused.txt", file_type="txt", status="ready")
        db.add(doc)
        db.commit()
        db.add(DocumentChunk(doc_id=doc.id, kb_id=doc.kb_id, content=ACL_CONTENT, embedding=[0.1] * settings.EMBEDDING_DIM,
                             meta={"is_public": is_public, "visible_roles": visible_roles, "policy_version": 1}, token_count=len(ACL_CONTENT)))
        db.commit()
    finally:
        db.close()
    return {**body, "id": created.json()["id"]}


def _set_policy(client, auth_headers, kb: dict, *, is_public: bool, visible_roles: list) -> None:
    body = {"name": kb["name"], "chunk_size": kb["chunk_size"], "chunk_overlap": kb["chunk_overlap"], "is_public": is_public, "visible_roles": visible_roles}
    r = client.put(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers, json=body)
    assert r.status_code == 200, r.text


def _search(client, headers, kb_id: int) -> dict:
    r = client.post(f"/api/v1/knowledge-bases/{kb_id}/search", headers=headers, json={"query": ACL_QUERY, "debug": True})
    assert r.status_code == 200, r.text
    return r.json()


def _contents(result: dict) -> list:
    return [item["content"] for item in result["items"]]


def test_restricting_kb_hides_existing_chunks_without_reprocess(client, auth_headers, developer_headers, offline_retrieval):
    """改成仅 admin 可见后不重新解析：developer 立刻检索不到存量切片，admin 不受影响；改回公开立刻恢复。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=True, visible_roles=[])
    try:
        assert _contents(_search(client, developer_headers, kb["id"])) == [ACL_CONTENT]
        _set_policy(client, auth_headers, kb, is_public=False, visible_roles=["admin"])
        denied = _search(client, developer_headers, kb["id"])
        assert denied["items"] == [] and denied["stats"]["kb_denied"] is True
        assert _contents(_search(client, auth_headers, kb["id"])) == [ACL_CONTENT]
        _set_policy(client, auth_headers, kb, is_public=True, visible_roles=[])
        assert _contents(_search(client, developer_headers, kb["id"])) == [ACL_CONTENT]
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)


def test_opening_kb_shows_chunks_ingested_while_restricted(client, auth_headers, developer_headers, offline_retrieval):
    """入库时仅 admin 可见（切片快照是受限的），改成公开后 developer 不用重新解析就能检索到。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=False, visible_roles=["admin"])
    try:
        assert _search(client, developer_headers, kb["id"])["items"] == []
        _set_policy(client, auth_headers, kb, is_public=True, visible_roles=[])
        opened = _search(client, developer_headers, kb["id"])
        assert _contents(opened) == [ACL_CONTENT] and opened["stats"]["kb_denied"] is False
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)


@pytest.mark.parametrize("role,is_public,visible_roles,expected", [
    ("admin", False, [], True),             # admin 不受限
    ("caller", True, [], True),             # 公开库
    ("caller", False, ["caller"], True),    # 在可见角色里
    ("caller", False, ["admin"], False),    # 不在可见角色里
    ("caller", False, None, False),         # 可见角色为空值
    (None, False, ["admin"], False),        # 没有角色
    (None, True, [], True),
])
def test_kb_allows_reads_current_policy(role, is_public, visible_roles, expected):
    kb = SimpleNamespace(id=1, is_public=is_public, visible_roles=visible_roles)
    assert retriever._kb_allows(role, kb) is expected


def test_missing_kb_is_denied_even_for_admin():
    assert retriever._kb_allows("admin", None) is False


def test_role_added_to_visible_roles_can_search_restricted_kb(client, auth_headers, developer_headers, offline_retrieval):
    """非公开库把 developer 加进可见角色后，developer 立刻能检索存量切片。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=False, visible_roles=["admin"])
    try:
        _set_policy(client, auth_headers, kb, is_public=False, visible_roles=["admin", "developer"])
        assert _contents(_search(client, developer_headers, kb["id"])) == [ACL_CONTENT]
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
