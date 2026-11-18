"""检索不可见与删除引用检查（docs/09 第 4 节待做项，2026-11-18）。

两件事各盯一组断言：

1. **库坏了要看得见**：知识库绑定的向量模型被停用/删除后，retriever 只让该库"不出结果"并记 warning ——
   对话里看着就是"知识库没有相关内容"，系统状态页也一切正常。现在要求这个信息一路带到用户能看见的地方：
   对话的 citations 事件带 `kb_unsearchable`（追加字段，不改既有字段）、检索审计里也留痕、
   `/system/status` 的 `unsearchable_kbs` 与 `degraded` 都能看出是哪个库、为什么。
2. **删除前查线上引用**：工具的删除只从草稿摘 id、知识库的删除完全不查引用，线上版本快照里的引用因此悬空、
   该工具/知识库从线上静默消失。现在被在线智能体的线上版本或已发布工作流的节点引用时 409 并点名引用方；
   草稿引用不拦，但删除时把它从草稿里摘掉，不留悬空 id（与 model_service.delete_model 同一口径）。
"""
import json
import uuid

from app.config import settings
from app.db.models import Agent, EmbeddingModel, Tool
from app.db.session import SessionLocal
from app.services import chat_service
from tests.conftest import publish_workflow
from tests.fakes import AnswerModel


def _uid() -> str:
    return uuid.uuid4().hex[:6]


def _make_model(client, auth_headers) -> dict:
    r = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-delref-model-" + _uid(), "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {},
    })
    assert r.status_code == 200, r.text
    return r.json()


def _make_embedding_model(client, auth_headers) -> dict:
    r = client.post("/api/v1/embedding-models", headers=auth_headers, json={
        "name": "pytest-delref-embed-" + _uid(), "provider": "openai", "api_base": "https://pytest.invalid/v1",
        "api_key": "pytest-key", "model_name": "pytest-embed-model", "dim": settings.EMBEDDING_DIM,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _make_kb(client, auth_headers, model_id: int) -> dict:
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": "pytest-delref-kb-" + _uid(), "description": "", "embedding_model_id": model_id,
        "chunk_size": 200, "chunk_overlap": 0,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _make_tool(client, auth_headers, name: str | None = None) -> dict:
    r = client.post("/api/v1/tools", headers=auth_headers, json={
        "name": name or "pytest-delref-tool-" + _uid(), "description": "", "type": "builtin", "config": {}, "timeout": 30,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _make_agent(client, auth_headers, model_id: int, **extra) -> dict:
    r = client.post("/api/v1/agents", headers=auth_headers, json={
        "name": "pytest-delref-agent-" + _uid(), "description": "", "system_prompt": "你是助手",
        "model_id": model_id, **extra,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _disable_embedding_model(model_id: int) -> None:
    """停用向量模型：接口会拒（还有库绑着），直接改库模拟"运维在页面上停用之前库就被绑着"或"行被删"的现场。"""
    db = SessionLocal()
    try:
        db.get(EmbeddingModel, model_id).is_enabled = False
        db.commit()
    finally:
        db.close()


def _debug_events(client, headers, agent_id: int, message: str) -> list:
    """装配页调试的 SSE 事件（**不建会话**）。

    这里不用线上对话接口：线上对话会建一条 title=首条消息的会话，而共享开发库上并发的另一个
    pytest 会话在做前置回收（按 pytest- 前缀整批删）时，可能恰好删掉本用例的智能体，
    级联带走会话 —— 表现为"messages 外键失败"，与本任务要验的东西无关（conftest 里同类说明见
    embedding_model fixture）。调试与线上共用 _context_from_config 与同一次检索装配，
    事件字段口径一致，验它足以覆盖"库不可检索要能被看见"。
    """
    r = client.post(f"/api/v1/agents/{agent_id}/debug-chat", headers=headers,
                    json={"message": message, "history": [], "config_source": "live"})
    assert r.status_code == 200, r.text
    events = [json.loads(p[6:]) for p in r.text.split("\n\n") if p.startswith("data: ")]
    assert events[-1]["type"] == "done", events[-1]
    return events


# ---------- 问题 1：库检索不了，用户要能看见原因 ----------

def test_chat_citations_expose_unsearchable_kb_with_reason(client, auth_headers, monkeypatch):
    """绑定的向量模型被停用后：该库不出引用，但 citations 事件要说明"是这个库检索不了、为什么"。

    2026-11-18 前只记一条 logger.warning，对话里就是"知识库没有相关内容"，没人能发现是配置坏了。
    """
    embedding = _make_embedding_model(client, auth_headers)
    kb = _make_kb(client, auth_headers, embedding["id"])
    model = _make_model(client, auth_headers)
    agent = _make_agent(client, auth_headers, model["id"], kb_ids=[kb["id"]])
    # 真走检索（不换 build_chat_context），只把模型换成桩：库不可检索时连查询向量都不会算，不会发网络请求
    monkeypatch.setattr(chat_service, "build_llm", lambda m, params=None: AnswerModel(messages=iter(["好的"])))
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "")
    try:
        assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).status_code == 200
        _disable_embedding_model(embedding["id"])

        events = _debug_events(client, auth_headers, agent["id"], "请假流程是什么")
        citations = next(e for e in events if e["type"] == "citations")
        assert citations["citations"] == []
        assert len(citations["kb_unsearchable"]) == 1, citations
        broken = citations["kb_unsearchable"][0]
        assert broken["kb_id"] == kb["id"] and broken["kb_name"] == kb["name"]
        assert "停用" in broken["reason"], broken["reason"]

        # 审计也要留痕：库坏了是"安静地少一段召回"，只写日志等于没人看得见
        db = SessionLocal()
        try:
            from app.db.models import AuditLog
            audit = (db.query(AuditLog).filter(AuditLog.action == "rag_retrieve", AuditLog.resource_id == agent["id"])
                     .order_by(AuditLog.id.desc()).first())
            assert audit is not None and audit.detail["kb_unsearchable"][0]["kb_id"] == kb["id"]
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{embedding['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


def test_retrieve_all_keeps_unsearchable_kb_without_kb_names(client, auth_headers, monkeypatch):
    """_retrieve_all 直接调用（线上对话 trace 关闭、kb_names 为空）也要把不可检索的库带出来。

    回归点：以前合并时只取 acl_rejected / rerank_mode，kb_unsearchable 被丢掉。
    """
    embedding = _make_embedding_model(client, auth_headers)
    kb = _make_kb(client, auth_headers, embedding["id"])
    try:
        _disable_embedding_model(embedding["id"])
        result = chat_service._retrieve_all([kb["id"]], ["随便问点什么"], "admin")
        assert result.citations == []
        # 库名由 _context_from_config 补（_retrieve_all 不额外查库，trace 关闭时线上不查库名）；
        # 这里只断言"不可检索的库被带出来了、原因正确、有可读标识"
        assert [e["kb_id"] for e in result.kb_unsearchable] == [kb["id"]]
        assert result.kb_unsearchable[0]["kb_name"] and "停用" in result.kb_unsearchable[0]["reason"]
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{embedding['id']}", headers=auth_headers)


def test_system_status_lists_unsearchable_kbs_and_degrades(client, auth_headers):
    """系统状态页要能看出"哪些库当前检索不了、为什么"：unsearchable_kbs 结构化清单 + degraded 一条一条列。"""
    embedding = _make_embedding_model(client, auth_headers)
    kb = _make_kb(client, auth_headers, embedding["id"])
    try:
        _disable_embedding_model(embedding["id"])
        body = client.get("/api/v1/system/status", headers=auth_headers).json()
        items = {i["id"]: i for i in body["unsearchable_kbs"]["items"]}
        assert kb["id"] in items, body["unsearchable_kbs"]
        assert items[kb["id"]]["name"] == kb["name"] and "停用" in items[kb["id"]]["reason"]
        assert body["unsearchable_kbs"]["total"] >= 1
        assert any(d["item"] == "kb_unsearchable" and kb["name"] in d["message"] for d in body["degraded"]), body["degraded"]
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{embedding['id']}", headers=auth_headers)


def test_system_status_has_no_unsearchable_kb_when_models_are_enabled(client, auth_headers):
    """正常库不进 unsearchable_kbs（否则状态页天天报"库坏了"，真出事时没人看）。"""
    embedding = _make_embedding_model(client, auth_headers)
    kb = _make_kb(client, auth_headers, embedding["id"])
    try:
        body = client.get("/api/v1/system/status", headers=auth_headers).json()
        assert kb["id"] not in {i["id"] for i in body["unsearchable_kbs"]["items"]}
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{embedding['id']}", headers=auth_headers)


# ---------- 问题 2：删除工具 / 知识库前查线上引用 ----------

def test_delete_tool_is_rejected_when_live_agent_version_references_it(client, auth_headers):
    """线上版本快照里绑着的工具不能删：快照不可变，删了它就从线上静默消失。409 要点名是哪个智能体。"""
    model = _make_model(client, auth_headers)
    tool = _make_tool(client, auth_headers)
    agent = _make_agent(client, auth_headers, model["id"], tool_ids=[tool["id"]])
    try:
        assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).status_code == 200
        r = client.delete(f"/api/v1/tools/{tool['id']}", headers=auth_headers)
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert agent["name"] in detail and "线上版本" in detail, detail
        # 工具还在，线上照常可用
        assert client.get(f"/api/v1/tools/{tool['id']}", headers=auth_headers).status_code == 200
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/tools/{tool['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


def test_delete_tool_detaches_draft_reference_and_succeeds(client, auth_headers):
    """只被草稿引用的工具照常能删，并且从草稿的 tool_ids 里摘掉，不留悬空 id。"""
    model = _make_model(client, auth_headers)
    tool = _make_tool(client, auth_headers)
    agent = _make_agent(client, auth_headers, model["id"], tool_ids=[tool["id"]])
    try:
        assert client.delete(f"/api/v1/tools/{tool['id']}", headers=auth_headers).status_code == 200
        db = SessionLocal()
        try:
            assert db.get(Agent, agent["id"]).tool_ids == []
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


def test_delete_tool_is_rejected_when_live_workflow_tool_node_references_it(client, auth_headers):
    """工作流的工具节点按名字引用工具；已发布工作流的线上快照里还挂着它时同样 409。"""
    tool = _make_tool(client, auth_headers)
    graph = {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text"}]}},
            {"id": "t", "type": "tool", "config": {"tool_name": tool["name"], "args": {}}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "t"}, {"from": "t", "to": "e"}],
    }
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-delref-wf-" + _uid(), "description": "", "graph": graph}).json()
    try:
        publish_workflow(client, auth_headers, wf["id"])
        r = client.delete(f"/api/v1/tools/{tool['id']}", headers=auth_headers)
        assert r.status_code == 409, r.text
        assert wf["name"] in r.json()["detail"] and "工作流" in r.json()["detail"]
    finally:
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)
        client.delete(f"/api/v1/tools/{tool['id']}", headers=auth_headers)


def test_delete_kb_is_rejected_when_live_agent_version_references_it(client, auth_headers):
    """线上版本快照里绑着的知识库不能删：删了之后检索只是安静地少一路召回，用户分不清是"库里没内容"还是"库没了"。"""
    embedding = _make_embedding_model(client, auth_headers)
    kb = _make_kb(client, auth_headers, embedding["id"])
    model = _make_model(client, auth_headers)
    agent = _make_agent(client, auth_headers, model["id"], kb_ids=[kb["id"]])
    try:
        assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).status_code == 200
        r = client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        assert r.status_code == 409, r.text
        assert agent["name"] in r.json()["detail"]
        assert client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers).status_code == 200
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{embedding['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


def test_delete_kb_detaches_draft_reference_and_succeeds(client, auth_headers):
    """只被草稿引用的知识库照常能删，并且从草稿的 kb_ids 里摘掉。"""
    embedding = _make_embedding_model(client, auth_headers)
    kb = _make_kb(client, auth_headers, embedding["id"])
    model = _make_model(client, auth_headers)
    agent = _make_agent(client, auth_headers, model["id"], kb_ids=[kb["id"]])
    try:
        assert client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers).status_code == 200
        db = SessionLocal()
        try:
            assert db.get(Agent, agent["id"]).kb_ids == []
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{embedding['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)


def test_delete_kb_is_rejected_when_live_workflow_kb_node_references_it(client, auth_headers):
    """已发布工作流的知识库检索节点还引用它时同样 409，并点名是哪个工作流。"""
    embedding = _make_embedding_model(client, auth_headers)
    kb = _make_kb(client, auth_headers, embedding["id"])
    graph = {
        "nodes": [
            {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text"}]}},
            {"id": "k", "type": "kb_retrieval", "config": {"kb_id": kb["id"], "top_k": 3}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "k"}, {"from": "k", "to": "e"}],
    }
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-delref-kbwf-" + _uid(), "description": "", "graph": graph}).json()
    try:
        publish_workflow(client, auth_headers, wf["id"])
        r = client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        assert r.status_code == 409, r.text
        assert wf["name"] in r.json()["detail"]
    finally:
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
        client.delete(f"/api/v1/embedding-models/{embedding['id']}", headers=auth_headers)
