"""API Key 资源作用域（docs/15 3.7.1，AC-028 ①③④⑤⑥）：Key 只能调授权的智能体与工作流，续跑只认自己发起的运行，
检索只放行公开库与 kb_ids 内且归属人可见的库；保存时作用域至少一项、引用须存在。模型换成桩，其余链路走真实代码。

会话通道隔离、end_user 与 client_message_id 幂等（AC-028 ②③ 的会话部分、⑦）见 test_api_key_conversations.py。
"""
import importlib.util
import json
import pathlib
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.config import settings
from app.db.models import Document, DocumentChunk, Run
from app.db.session import SessionLocal, engine
from app.rag import retriever
from app.services import chat_service
from tests.fakes import AnswerModel

KEYS = "/api/v1/api-keys"
CONTENT = "智枢报销流程：发票先交财务初审再由部门负责人签字"
QUERY = "报销流程"
REVIEW_GRAPH = {
    "nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "r", "type": "human_review", "config": {"instruction": "请审核"}},
              {"id": "e", "type": "end", "config": {}}],
    "edges": [{"from": "s", "to": "r"}, {"from": "r", "to": "e"}],
}


def _uid() -> str:
    return uuid.uuid4().hex[:6]


def _bearer(key: dict) -> dict:
    return {"Authorization": "Bearer " + key["key"]}


@pytest.fixture
def made(client, auth_headers):
    """登记本用例建的对象，结束时按 Key → 智能体 → 工作流 → 知识库 → 模型的顺序删掉。"""
    bag = {"keys": [], "agents": [], "workflows": [], "kbs": [], "models": []}
    yield bag
    for kind, path in (("keys", KEYS), ("agents", "/api/v1/agents"), ("workflows", "/api/v1/workflows"),
                       ("kbs", "/api/v1/knowledge-bases"), ("models", "/api/v1/models")):
        for oid in bag[kind]:
            client.delete(f"{path}/{oid}", headers=auth_headers)


def _key(client, headers, made, **scope) -> dict:
    r = client.post(KEYS, headers=headers, json={"name": "pytest-scope-" + _uid(), "quota": 50, **scope})
    assert r.status_code == 200, r.text
    made["keys"].append(r.json()["id"])
    return r.json()


def _model(client, auth_headers, made) -> int:
    r = client.post("/api/v1/models", headers=auth_headers, json={"name": "pytest-scope-model-" + _uid(), "provider": "openai",
                                                                  "api_base": "http://upstream.test/v1", "api_key": "sk-test", "model_name": "x", "default_params": {}})
    assert r.status_code == 200, r.text
    made["models"].append(r.json()["id"])
    return r.json()["id"]


def _published_agent(client, auth_headers, made, model_id: int, kb_ids: list | None = None) -> int:
    r = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-scope-agent-" + _uid(), "description": "", "system_prompt": "你是助手",
                                                                  "model_id": model_id, "kb_ids": kb_ids or []})
    assert r.status_code == 200, r.text
    made["agents"].append(r.json()["id"])
    assert client.post(f"/api/v1/agents/{r.json()['id']}/publish", headers=auth_headers).status_code == 200
    return r.json()["id"]


def _kb_with_chunk(client, auth_headers, made, *, is_public: bool, visible_roles: list) -> int:
    """建库并直接插一条切片（不走 MinIO 与解析）。"""
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": "pytest-scope-kb-" + _uid(), "chunk_size": 200, "chunk_overlap": 0,
                                                                            "is_public": is_public, "visible_roles": visible_roles})
    assert r.status_code == 200, r.text
    kb_id = r.json()["id"]
    made["kbs"].append(kb_id)
    db = SessionLocal()
    try:
        doc = Document(kb_id=kb_id, name="pytest-scope.txt", file_path="pytest/unused.txt", file_type="txt", status="ready")
        db.add(doc)
        db.commit()
        db.add(DocumentChunk(doc_id=doc.id, kb_id=kb_id, content=CONTENT, embedding=[0.1] * settings.EMBEDDING_DIM, meta={}, token_count=len(CONTENT)))
        db.commit()
    finally:
        db.close()
    return kb_id


@pytest.fixture
def stub_llm_and_retrieval(monkeypatch):
    """模型换成桩，检索的查询向量打桩、重排走词法（不连外部服务）。"""
    monkeypatch.setattr(chat_service, "build_llm", lambda model, params=None: AnswerModel(messages=iter(["好的"])))
    monkeypatch.setattr(retriever, "embed_query", lambda t: [0.1] * settings.EMBEDDING_DIM)
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "")


def _chat(client, headers, agent_id: int, message: str = "你好"):
    return client.post(f"/api/v1/agents/{agent_id}/chat", headers=headers, json={"message": message})


def _events(resp) -> list[dict]:
    return [json.loads(p[6:]) for p in resp.text.split("\n\n") if p.startswith("data: ")]


def _runs(**filters) -> list[Run]:
    db = SessionLocal()
    try:
        return db.query(Run).filter_by(**filters).order_by(Run.id).all()
    finally:
        db.close()


# ---------- 保存时的作用域校验（AC-028 ③） ----------

def test_key_without_any_scope_is_rejected(client, auth_headers, made):
    r = client.post(KEYS, headers=auth_headers, json={"name": "pytest-scope-empty-" + _uid()})
    if r.status_code == 200:  # 应被拒却建出来了：先登记删除再让断言失败
        made["keys"].append(r.json()["id"])
    assert r.status_code == 400 and "至少授权一个" in r.json()["detail"]


def test_key_scope_must_reference_existing_resources(client, auth_headers, made):
    r = client.post(KEYS, headers=auth_headers, json={"name": "pytest-scope-ghost-" + _uid(), "agent_ids": [999999991, 999999992]})
    if r.status_code == 200:
        made["keys"].append(r.json()["id"])
    assert r.status_code == 400 and r.json()["detail"] == "智能体不存在：999999991, 999999992"
    wf = client.post(KEYS, headers=auth_headers, json={"name": "pytest-scope-ghost-" + _uid(), "workflow_ids": [999999993]})
    if wf.status_code == 200:
        made["keys"].append(wf.json()["id"])
    assert wf.status_code == 400 and wf.json()["detail"] == "工作流不存在：999999993"


def test_key_kb_scope_must_be_visible_to_its_owner(client, auth_headers, made):
    """developer 给自己的 Key 授权一个仅 admin 可见的库 → 400，与不存在同一句（KB-01 的可见性）；admin 自己可以。"""
    hidden = _kb_with_chunk(client, auth_headers, made, is_public=False, visible_roles=["admin"])
    name = "pytest-scope-dev-" + _uid()
    user = client.post("/api/v1/users", headers=auth_headers, json={"username": name, "password": "dev12345", "role": "developer"}).json()
    try:
        dev = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"username": name, "password": "dev12345"}).json()["token"]}
        r = client.post(KEYS, headers=dev, json={"name": "pytest-scope-devkey-" + _uid(), "kb_ids": [hidden]})
        assert r.status_code == 400 and r.json()["detail"] == f"知识库不存在：{hidden}"
        assert _key(client, auth_headers, made, kb_ids=[hidden])["kb_ids"] == [hidden]
    finally:
        client.delete(f"/api/v1/users/{user['id']}", headers=auth_headers)  # 用户删除连带删掉它可能建出的 Key


def test_updating_scope_to_empty_is_rejected_and_keeps_old_scope(client, auth_headers, made, key_scope):
    key = _key(client, auth_headers, made, **key_scope)
    r = client.put(f"{KEYS}/{key['id']}", headers=auth_headers, json={"workflow_ids": []})
    assert r.status_code == 400
    row = next(k for k in client.get(KEYS, headers=auth_headers, params={"q": key["name"]}).json()["items"])
    assert row["workflow_ids"] == key_scope["workflow_ids"]
    assert row["scope"]["workflows"][0]["id"] == key_scope["workflow_ids"][0] and row["scope"]["workflows"][0]["name"]


# ---------- 智能体作用域（AC-028 ①） ----------

def test_key_can_only_chat_with_agents_in_scope(client, auth_headers, made, stub_llm_and_retrieval):
    model_id = _model(client, auth_headers, made)
    a, b = _published_agent(client, auth_headers, made, model_id), _published_agent(client, auth_headers, made, model_id)
    key = _key(client, auth_headers, made, agent_ids=[a])
    ok = _chat(client, _bearer(key), a)
    assert ok.status_code == 200 and _events(ok)[-1]["type"] == "done"
    assert [(r.source, r.api_key_id) for r in _runs(agent_id=a)] == [("api_key", key["id"])]
    denied = _chat(client, _bearer(key), b)
    assert denied.status_code == 403 and denied.json()["detail"] == "该 API Key 无权调用此智能体"
    assert _runs(agent_id=b) == []  # 拒绝在写库之前
    listed = client.get("/api/v1/agents/available", headers=_bearer(key), params={"page_size": 100}).json()["items"]
    assert [x["id"] for x in listed] == [a]
    assert client.get(f"/api/v1/agents/available/{b}", headers=_bearer(key)).status_code == 403
    assert client.get(f"/api/v1/agents/available/{a}", headers=_bearer(key)).status_code == 200


# ---------- 工作流作用域与续跑（AC-028 ⑤） ----------

def test_key_without_workflow_scope_cannot_run_it(client, auth_headers, made):
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-scope-wf-" + _uid(), "description": "", "graph": REVIEW_GRAPH}).json()
    made["workflows"].append(wf["id"])
    model_id = _model(client, auth_headers, made)
    key = _key(client, auth_headers, made, agent_ids=[_published_agent(client, auth_headers, made, model_id)])
    r = client.post(f"/api/v1/workflows/{wf['id']}/run", headers=_bearer(key), json={"input": "x"})
    assert r.status_code == 403 and r.json()["detail"] == "该 API Key 无权调用此工作流"
    assert _runs(workflow_id=wf["id"]) == []


def test_key_can_only_resume_runs_it_started(client, auth_headers, made):
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-scope-review-" + _uid(), "description": "", "graph": REVIEW_GRAPH}).json()
    made["workflows"].append(wf["id"])
    mine, other = _key(client, auth_headers, made, workflow_ids=[wf["id"]]), _key(client, auth_headers, made, workflow_ids=[wf["id"]])
    run_url = f"/api/v1/workflows/{wf['id']}/run"
    by_key = client.post(run_url, headers=_bearer(mine), json={"input": "x"}).json()
    by_ui = client.post(run_url, headers=auth_headers, json={"input": "x"}).json()
    assert by_key["status"] == by_ui["status"] == "awaiting_review"
    resume = lambda run_id, headers: client.post(f"/api/v1/workflows/{wf['id']}/runs/{run_id}/resume", headers=headers, json={"decision": {"approved": True}})
    for run_id, headers in ((by_key["run_id"], _bearer(other)), (by_ui["run_id"], _bearer(mine))):
        denied = resume(run_id, headers)
        assert denied.status_code == 404 and denied.json()["detail"] == "运行记录不存在"
    assert {r.id: r.status for r in _runs(workflow_id=wf["id"])} == {by_key["run_id"]: "awaiting_review", by_ui["run_id"]: "awaiting_review"}
    assert resume(by_key["run_id"], _bearer(mine)).json()["status"] == "success"
    assert resume(by_ui["run_id"], auth_headers).json()["status"] == "success"  # 登录续跑的口径不变


# ---------- Key 对话的检索身份（AC-028 ⑥） ----------

def test_admin_key_does_not_unlock_restricted_kb_outside_its_kb_scope(client, auth_headers, made, stub_llm_and_retrieval):
    """admin 名下的 Key 只授权智能体 A（A 绑定仅 admin 可见的库 K、kb_ids 为空）：引用不到 K；把 K 加进 kb_ids 后能引用。
    同时绑定的公开库不受影响。2026-10-05 前归属人是 admin 时检索完全不过滤。"""
    model_id = _model(client, auth_headers, made)
    restricted = _kb_with_chunk(client, auth_headers, made, is_public=False, visible_roles=["admin"])
    agent = _published_agent(client, auth_headers, made, model_id, kb_ids=[restricted])
    key = _key(client, auth_headers, made, agent_ids=[agent])

    def cited(headers) -> list:
        events = _events(_chat(client, headers, agent, QUERY))
        assert events[-1]["type"] == "done", events[-1]
        return [c["kb_id"] for e in events if e["type"] == "citations" for c in e["citations"]]

    assert cited(_bearer(key)) == []
    assert cited(auth_headers) == [restricted]  # 登录对话按角色，admin 照常能引用
    assert client.put(f"{KEYS}/{key['id']}", headers=auth_headers, json={"kb_ids": [restricted]}).status_code == 200
    assert cited(_bearer(key)) == [restricted]

    public = _kb_with_chunk(client, auth_headers, made, is_public=True, visible_roles=[])
    open_agent = _published_agent(client, auth_headers, made, model_id, kb_ids=[public])
    open_key = _key(client, auth_headers, made, agent_ids=[open_agent])
    events = _events(_chat(client, _bearer(open_key), open_agent, QUERY))
    assert [c["kb_id"] for e in events if e["type"] == "citations" for c in e["citations"]] == [public]


@pytest.mark.parametrize("is_public,roles,in_scope,owner,expected", [
    (True, [], False, "caller", True),          # 公开库不看范围
    (False, ["admin"], False, "admin", False),  # admin 的 Key 也不放行范围外的受限库
    (False, ["admin"], True, "admin", True),
    (False, ["admin"], True, "developer", False),  # 在范围内但归属人看不到
    (False, ["developer"], True, "developer", True),
])
def test_kb_allows_with_key_scope(is_public, roles, in_scope, owner, expected):
    kb = SimpleNamespace(id=7, is_public=is_public, visible_roles=roles)
    assert retriever.kb_allows(owner, kb, [7] if in_scope else []) is expected


# ---------- 迁移预览（AC-028 ④；--apply 会停用共享库里真实的 Key，用例只测预览） ----------

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrations" / "20261005_183713_71b564_api_key_scopes_and_conversation_channel.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m2a_api_key_scopes", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preview_lists_keys_without_any_scope(client, auth_headers, made, key_scope):
    scoped = _key(client, auth_headers, made, **key_scope)
    db = SessionLocal()
    try:
        bare_id = db.execute(text("INSERT INTO api_keys (user_id, name, key_prefix, key_hash, is_enabled, quota, used, allowed_ips, rate_limit_per_minute) "
                                  "SELECT id, 'pytest-scope-bare', 'ak_bare...', :h, true, 1, 0, '[]', 0 FROM users WHERE username = 'admin' RETURNING id"),
                             {"h": "pytest-" + _uid()}).scalar()
        db.commit()
        made["keys"].append(bare_id)
    finally:
        db.close()
    with engine.connect() as conn:
        ids = {k["id"] for k in _migration().unscoped_keys(conn)}
    assert bare_id in ids and scoped["id"] not in ids
