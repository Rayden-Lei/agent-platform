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
    r = client.put(f"/api/v1/knowledge-bases/{kb['id']}/access", headers=auth_headers, json={"is_public": is_public, "visible_roles": visible_roles})
    assert r.status_code == 200, r.text


def _search(client, headers, kb_id: int) -> dict:
    r = client.post(f"/api/v1/knowledge-bases/{kb_id}/search", headers=headers, json={"query": ACL_QUERY, "debug": True})
    assert r.status_code == 200, r.text
    return r.json()


def _contents(result: dict) -> list:
    return [item["content"] for item in result["items"]]


def _search_status(client, headers, kb_id: int) -> int:
    return client.post(f"/api/v1/knowledge-bases/{kb_id}/search", headers=headers, json={"query": ACL_QUERY, "debug": True}).status_code


def test_restricting_kb_hides_existing_chunks_without_reprocess(client, auth_headers, developer_headers, offline_retrieval):
    """改成仅 admin 可见后不重新解析：developer 立刻检索不到存量切片（2026-10-05 起管理面对不可见的库一律 404，
    此前是 200 + kb_denied），admin 不受影响；改回公开立刻恢复。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=True, visible_roles=[])
    try:
        assert _contents(_search(client, developer_headers, kb["id"])) == [ACL_CONTENT]
        _set_policy(client, auth_headers, kb, is_public=False, visible_roles=["admin"])
        assert _search_status(client, developer_headers, kb["id"]) == 404
        assert _contents(_search(client, auth_headers, kb["id"])) == [ACL_CONTENT]
        _set_policy(client, auth_headers, kb, is_public=True, visible_roles=[])
        assert _contents(_search(client, developer_headers, kb["id"])) == [ACL_CONTENT]
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)


def test_opening_kb_shows_chunks_ingested_while_restricted(client, auth_headers, developer_headers, offline_retrieval):
    """入库时仅 admin 可见（切片快照是受限的），改成公开后 developer 不用重新解析就能检索到。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=False, visible_roles=["admin"])
    try:
        assert _search_status(client, developer_headers, kb["id"]) == 404
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
    assert retriever.kb_allows(role, kb) is expected


def test_missing_kb_is_denied_even_for_admin():
    assert retriever.kb_allows("admin", None) is False


def test_role_added_to_visible_roles_can_search_restricted_kb(client, auth_headers, developer_headers, offline_retrieval):
    """非公开库把 developer 加进可见角色后，developer 立刻能检索存量切片。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=False, visible_roles=["admin"])
    try:
        _set_policy(client, auth_headers, kb, is_public=False, visible_roles=["admin", "developer"])
        assert _contents(_search(client, developer_headers, kb["id"])) == [ACL_CONTENT]
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)


# ---------- 管理面按可见性鉴权、权限保存约束、审计、对话路径（docs/15 KB-01，AC-030；2026-10-05） ----------

import json  # noqa: E402

from app.api.v1 import kb as kb_route  # noqa: E402
from app.services import chat_service, kb_service  # noqa: E402
from tests.fakes import AnswerModel  # noqa: E402

KB = "/api/v1/knowledge-bases"


def _doc_id(kb_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(Document.id).filter(Document.kb_id == kb_id).scalar()
    finally:
        db.close()


def _audits(client, auth_headers, resource: str, resource_id: int, action: str) -> list:
    r = client.get("/api/v1/audit-logs", headers=auth_headers, params={"resource": resource, "resource_id": resource_id, "action": action, "page_size": 20})
    assert r.status_code == 200, r.text
    return r.json()["items"]


@pytest.fixture
def no_storage(monkeypatch):
    """上传与后台处理打桩：不写 MinIO、不解析。"""
    monkeypatch.setattr(kb_service, "upload_file", lambda name, data, ctype: None)
    monkeypatch.setattr(kb_route, "process_document", lambda doc_id, *args: None)


@pytest.fixture
def chat_model(client, auth_headers):
    r = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-kb-acl-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {},
    })
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"/api/v1/models/{r.json()['id']}", headers=auth_headers)


def test_hidden_kb_is_404_on_every_management_endpoint(client, auth_headers, developer_headers, no_storage):
    """AC-030 ②：不在可见角色里的 developer 调详情、改、删、文档、切片、上传、检索、续处理、重新解析、批量一律 404，列表里也看不到；
    admin 不受影响，库和文档都还在。2026-10-05 前这些接口只看角色，developer 能读能删仅 admin 可见的库。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=False, visible_roles=["admin"])
    kid, did = kb["id"], _doc_id(kb["id"])
    try:
        listed = client.get(KB, headers=developer_headers, params={"q": kb["name"]}).json()
        assert listed["total"] == 0 and listed["items"] == []
        body = {k: kb[k] for k in ("name", "chunk_size", "chunk_overlap")}
        calls = [
            ("GET", f"{KB}/{kid}", None), ("PUT", f"{KB}/{kid}", body),
            ("PUT", f"{KB}/{kid}/access", {"is_public": True}), ("GET", f"{KB}/{kid}/access-log", None),
            ("GET", f"{KB}/{kid}/documents", None), ("GET", f"{KB}/{kid}/documents/{did}/chunks", None),
            ("POST", f"{KB}/{kid}/search", {"query": ACL_QUERY}), ("POST", f"{KB}/{kid}/documents/{did}/reprocess", None),
            ("POST", f"{KB}/{kid}/documents/{did}/resume", None), ("POST", f"{KB}/{kid}/documents/batch", {"ids": [did], "action": "delete"}),
            ("DELETE", f"{KB}/{kid}/documents/{did}", None), ("DELETE", f"{KB}/{kid}", None),
        ]
        statuses = {f"{m} {u}": client.request(m, u, headers=developer_headers, json=b).status_code for m, u, b in calls}
        assert set(statuses.values()) == {404}, statuses
        upload = client.post(f"{KB}/{kid}/documents", headers=developer_headers, files={"file": ("a.txt", b"hello", "text/plain")})
        assert upload.status_code == 404
        batch = client.post(f"{KB}/batch", headers=developer_headers, json={"ids": [kid], "action": "delete"}).json()
        assert batch["succeeded"] == [] and batch["failed"] == [{"id": kid, "detail": "知识库不存在"}]
        detail = client.get(f"{KB}/{kid}", headers=auth_headers)
        assert detail.status_code == 200 and detail.json()["document_count"] == 1 and detail.json()["chunk_count"] == 1
    finally:
        client.delete(f"{KB}/{kid}", headers=auth_headers)


def test_kb_list_for_developer_follows_the_retrieval_rule(client, auth_headers, developer_headers):
    """列表的可见性过滤与检索闸门 kb_allows 同一口径：公开库、可见角色含 developer 的库看得到，仅 admin 的看不到。"""
    prefix = "pytest-kb-vis-" + uuid.uuid4().hex[:6]
    policies = {"public": (True, []), "dev": (False, ["developer"]), "admin": (False, ["admin"])}
    ids = {}
    try:
        for key, (is_public, roles) in policies.items():
            r = client.post(KB, headers=auth_headers, json={"name": f"{prefix}-{key}", "chunk_size": 200, "chunk_overlap": 0, "is_public": is_public, "visible_roles": roles})
            ids[key] = r.json()["id"]
        seen = {item["id"] for item in client.get(KB, headers=developer_headers, params={"q": prefix}).json()["items"]}
        expected = {ids[k] for k, (p, roles) in policies.items() if retriever.kb_allows("developer", SimpleNamespace(is_public=p, visible_roles=roles))}
        assert seen == expected == {ids["public"], ids["dev"]}
        assert {item["id"] for item in client.get(KB, headers=auth_headers, params={"q": prefix}).json()["items"]} == set(ids.values())
    finally:
        for kid in ids.values():
            client.delete(f"{KB}/{kid}", headers=auth_headers)


def test_developer_cannot_save_a_policy_that_shuts_developers_out(client, auth_headers, developer_headers):
    """AC-030 ③：非 admin 保存把自己排除在外的权限 400，且不落库；admin 不受此限。"""
    name = "pytest-kb-self-" + uuid.uuid4().hex[:6]
    base = {"name": name, "chunk_size": 200, "chunk_overlap": 0}
    rejected = client.post(KB, headers=developer_headers, json={**base, "is_public": False, "visible_roles": ["admin"]})
    if rejected.status_code == 200:  # 应被拒却建出来了：先删掉再让断言失败，不在共享库留数据
        client.delete(f"{KB}/{rejected.json()['id']}", headers=auth_headers)
    assert rejected.status_code == 400 and "不能把自己" in rejected.json()["detail"]
    assert client.get(KB, headers=auth_headers, params={"q": name}).json()["total"] == 0
    created = client.post(KB, headers=developer_headers, json={**base, "is_public": False, "visible_roles": ["developer"]})
    assert created.status_code == 200, created.text
    kid = created.json()["id"]
    try:
        narrowed = client.put(f"{KB}/{kid}/access", headers=developer_headers, json={"is_public": False, "visible_roles": ["admin"]})
        assert narrowed.status_code == 400
        assert client.get(f"{KB}/{kid}", headers=auth_headers).json()["visible_roles"] == ["developer"]
        assert client.put(f"{KB}/{kid}/access", headers=auth_headers, json={"is_public": False, "visible_roles": ["admin"]}).status_code == 200
    finally:
        client.delete(f"{KB}/{kid}", headers=auth_headers)


def test_kb_create_update_delete_are_audited_with_policy_before_and_after(client, auth_headers, developer_headers):
    """AC-030 ③ 后半：改权限产生审计（update_access）且 detail 有改前改后，变更记录接口按新到旧列出；
    改名称写 update 只记改了哪些字段；没变化的保存不写审计；新建、删除也留痕。2026-10-05 前知识库的增删改不写审计。"""
    body = {"name": "pytest-kb-audit-" + uuid.uuid4().hex[:6], "chunk_size": 200, "chunk_overlap": 0, "is_public": True, "visible_roles": []}
    kid = client.post(KB, headers=auth_headers, json=body).json()["id"]
    try:
        before, after = {"is_public": True, "visible_roles": []}, {"is_public": False, "visible_roles": ["admin", "developer"]}
        assert client.put(f"{KB}/{kid}/access", headers=developer_headers, json=after).status_code == 200
        assert client.put(f"{KB}/{kid}/access", headers=auth_headers, json=after).status_code == 200  # 没变化：不再记一条
        assert [a["detail"]["name"] for a in _audits(client, auth_headers, "knowledge_base", kid, "create")] == [body["name"]]
        (change,) = _audits(client, auth_headers, "knowledge_base", kid, "update_access")
        assert change["username"].startswith("pytest-kb-dev-") and (change["detail"]["before"], change["detail"]["after"]) == (before, after)
        log = client.get(f"{KB}/{kid}/access-log", headers=developer_headers).json()["items"]
        assert [(e["action"], e["before"], e["after"]) for e in log] == [("update_access", before, after), ("create", None, before)]
        assert "ip" not in log[0]
        renamed = {k: body[k] for k in ("chunk_size", "chunk_overlap")} | {"name": body["name"] + "-x"}
        assert client.put(f"{KB}/{kid}", headers=auth_headers, json=renamed).status_code == 200
        assert client.put(f"{KB}/{kid}", headers=auth_headers, json=renamed).status_code == 200
        assert [a["detail"]["changed"] for a in _audits(client, auth_headers, "knowledge_base", kid, "update")] == [["name"]]
    finally:
        assert client.delete(f"{KB}/{kid}", headers=auth_headers).status_code == 200
    assert [a["detail"]["name"] for a in _audits(client, auth_headers, "knowledge_base", kid, "delete")] == [body["name"] + "-x"]


def test_updating_kb_no_longer_accepts_policy_fields(client, auth_headers):
    """契约一次切换（2026-10-05）：PUT /{id} 不再接收权限与向量模型，带了 422 且什么都没改，不悄悄忽略 ——
    此前整体覆盖，只想改名称的保存会把别人刚改的权限盖回去。权限走 PUT /{id}/access。"""
    body = {"name": "pytest-kb-put-" + uuid.uuid4().hex[:6], "chunk_size": 200, "chunk_overlap": 0}
    kid = client.post(KB, headers=auth_headers, json={**body, "is_public": False, "visible_roles": ["admin"]}).json()["id"]
    try:
        for extra in ({"is_public": True}, {"visible_roles": ["caller"]}, {"embedding_model": "x"}):
            assert client.put(f"{KB}/{kid}", headers=auth_headers, json={**body, "name": body["name"] + "-x", **extra}).status_code == 422, extra
        kb = client.get(f"{KB}/{kid}", headers=auth_headers).json()
        assert (kb["name"], kb["is_public"], kb["visible_roles"]) == (body["name"], False, ["admin"])
    finally:
        client.delete(f"{KB}/{kid}", headers=auth_headers)


def test_detail_says_who_can_retrieve_and_which_agents_bind_it_online(client, auth_headers, chat_model):
    """详情的 access 由检索闸门算（前端不另写规则）；绑定清单含线上版本的绑定：草稿已解绑、线上还绑着的智能体仍列出且 in_live。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=False, visible_roles=["admin"])
    agent_id = None
    try:
        detail = client.get(f"{KB}/{kb['id']}", headers=auth_headers).json()
        assert detail["access"] == {"admin": True, "developer": False, "caller": False, "anonymous": False}
        _set_policy(client, auth_headers, kb, is_public=True, visible_roles=[])
        assert client.get(f"{KB}/{kb['id']}", headers=auth_headers).json()["access"] == {"admin": True, "developer": True, "caller": True, "anonymous": True}
        base = {"name": "pytest-kb-live-" + uuid.uuid4().hex[:6], "description": "", "system_prompt": "你是助手", "model_id": chat_model["id"]}
        agent_id = client.post("/api/v1/agents", headers=auth_headers, json={**base, "kb_ids": [kb["id"]]}).json()["id"]
        assert client.post(f"/api/v1/agents/{agent_id}/publish", headers=auth_headers).status_code == 200
        current = client.get(f"/api/v1/agents/{agent_id}", headers=auth_headers).json()
        assert client.put(f"/api/v1/agents/{agent_id}", headers=auth_headers, json={**base, "kb_ids": [], "expected_updated_at": current["updated_at"]}).status_code == 200
        (bound,) = client.get(f"{KB}/{kb['id']}", headers=auth_headers).json()["agents"]
        assert (bound["id"], bound["status"], bound["in_draft"], bound["in_live"]) == (agent_id, "published", False, True)
    finally:
        if agent_id:
            client.delete(f"/api/v1/agents/{agent_id}", headers=auth_headers)
        client.delete(f"{KB}/{kb['id']}", headers=auth_headers)


def test_document_operations_are_audited(client, auth_headers, no_storage):
    """文档上传、重新解析、续处理、删除都写审计（resource=document，detail 带知识库与文件名）。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=True, visible_roles=[])
    kid, did = kb["id"], _doc_id(kb["id"])
    try:
        up = client.post(f"{KB}/{kid}/documents", headers=auth_headers, files={"file": ("pytest-audit.txt", b"hello", "text/plain")})
        assert up.status_code == 200, up.text
        assert [a["detail"] for a in _audits(client, auth_headers, "document", up.json()["id"], "upload")] == [{"kb_id": kid, "name": "pytest-audit.txt"}]
        assert client.post(f"{KB}/{kid}/documents/{did}/reprocess", headers=auth_headers).status_code == 200
        db = SessionLocal()
        try:
            db.get(Document, did).status = "failed"  # 重新解析后没有真的跑处理（已打桩）；置为失败才能续处理
            db.commit()
        finally:
            db.close()
        assert client.post(f"{KB}/{kid}/documents/{did}/resume", headers=auth_headers).status_code == 200
        assert client.delete(f"{KB}/{kid}/documents/{did}", headers=auth_headers).status_code == 200
        for action in ("reprocess", "resume", "delete"):
            assert [a["detail"] for a in _audits(client, auth_headers, "document", did, action)] == [{"kb_id": kid, "name": "pytest-acl.txt"}], action
    finally:
        client.delete(f"{KB}/{kid}", headers=auth_headers)


def test_caller_chat_stops_citing_a_kb_once_it_is_restricted(client, auth_headers, caller_headers, chat_model, offline_retrieval, monkeypatch):
    """AC-030 ① 的对话路径：已发布、绑定公开库的智能体，调用者对话能引用该库；把库改成仅 admin 可见、不重新解析，
    调用者立刻引用不到，admin 仍能引用；改回公开立即恢复。模型换成桩，检索走真实代码。"""
    kb = _kb_with_one_chunk(client, auth_headers, is_public=True, visible_roles=[])
    agent = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-kb-acl-agent-" + uuid.uuid4().hex[:6], "description": "",
                                                                       "system_prompt": "你是助手", "model_id": chat_model["id"], "kb_ids": [kb["id"]]}).json()
    monkeypatch.setattr(chat_service, "build_llm", lambda model, params=None: AnswerModel(messages=iter(["好的"])))

    def cited(headers) -> list:
        resp = client.post(f"/api/v1/agents/{agent['id']}/chat", headers=headers, json={"message": ACL_QUERY})
        assert resp.status_code == 200, resp.text
        events = [json.loads(p[6:]) for p in resp.text.split("\n\n") if p.startswith("data: ")]
        assert events[-1]["type"] == "done", events[-1]
        return [c["content"] for e in events if e["type"] == "citations" for c in e["citations"]]

    try:
        assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).status_code == 200
        assert cited(caller_headers) == [ACL_CONTENT]
        _set_policy(client, auth_headers, kb, is_public=False, visible_roles=["admin"])
        assert cited(caller_headers) == []
        assert cited(auth_headers) == [ACL_CONTENT]
        _set_policy(client, auth_headers, kb, is_public=True, visible_roles=[])
        assert cited(caller_headers) == [ACL_CONTENT]
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"{KB}/{kb['id']}", headers=auth_headers)


def test_developer_cannot_bind_a_kb_they_cannot_see(client, auth_headers, developer_headers, chat_model):
    """保存智能体时新增绑定的知识库须对保存人可见（docs/15 3.3 / KB-01），不可见与不存在同一句提示、不暴露库是否存在；
    admin 绑上的受限库，developer 只改提示词照样能保存（已有绑定不追溯）。"""
    hidden = _kb_with_one_chunk(client, auth_headers, is_public=False, visible_roles=["admin"])
    other = _kb_with_one_chunk(client, auth_headers, is_public=False, visible_roles=["admin"])
    base = {"name": "pytest-kb-bind-" + uuid.uuid4().hex[:6], "description": "", "system_prompt": "你是助手", "model_id": chat_model["id"]}
    agent_id = None
    try:
        r = client.post("/api/v1/agents", headers=developer_headers, json={**base, "kb_ids": [hidden["id"]]})
        if r.status_code == 200:  # 应被拒却建出来了：先删掉再让断言失败
            client.delete(f"/api/v1/agents/{r.json()['id']}", headers=auth_headers)
        assert r.status_code == 400 and r.json()["detail"] == f"知识库不存在：{hidden['id']}"
        created = client.post("/api/v1/agents", headers=auth_headers, json={**base, "kb_ids": [hidden["id"]]})
        assert created.status_code == 200, created.text
        agent_id = created.json()["id"]
        current = client.get(f"/api/v1/agents/{agent_id}", headers=auth_headers).json()
        keep = client.put(f"/api/v1/agents/{agent_id}", headers=developer_headers,
                          json={**base, "system_prompt": "改过的提示词", "kb_ids": [hidden["id"]], "expected_updated_at": current["updated_at"]})
        assert keep.status_code == 200, keep.text
        current = client.get(f"/api/v1/agents/{agent_id}", headers=auth_headers).json()
        add = client.put(f"/api/v1/agents/{agent_id}", headers=developer_headers,
                         json={**base, "kb_ids": [hidden["id"], other["id"]], "expected_updated_at": current["updated_at"]})
        assert add.status_code == 400 and add.json()["detail"] == f"知识库不存在：{other['id']}"
    finally:
        if agent_id:
            client.delete(f"/api/v1/agents/{agent_id}", headers=auth_headers)
        client.delete(f"{KB}/{hidden['id']}", headers=auth_headers)
        client.delete(f"{KB}/{other['id']}", headers=auth_headers)
