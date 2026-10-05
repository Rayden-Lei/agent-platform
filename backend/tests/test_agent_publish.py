"""发布语义（docs/15 3.2，FR-039；AC-020）与保存校验（3.3，AC-021 后端部分）。

草稿（agents 行）与线上（published_version 指向的不可变快照）分离：保存只改草稿，发布才替换线上；
恢复到草稿不动线上，回滚上线不动草稿；下线后对外入口 403。对话用 tests/fakes 的模型桩，不发网络请求。
"""
import threading
import uuid

import pytest

from app.db.models import AgentVersion, AuditLog, Run, User
from app.db.session import SessionLocal
from app.services import agent_service, chat_service, conversation_service
from tests.fakes import AnswerModel, use_llm


def _uid() -> str:
    return uuid.uuid4().hex[:6]


def _new_model(client, auth_headers) -> dict:
    r = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-pub-model-" + _uid(), "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {},
    })
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def model(client, auth_headers):
    m = _new_model(client, auth_headers)
    yield m
    client.delete(f"/api/v1/models/{m['id']}", headers=auth_headers)


@pytest.fixture
def make_agent(client, auth_headers, model):
    created: list[int] = []

    def _make(prompt: str = "标记A", publish: bool = True) -> dict:
        r = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-pub-" + _uid(), "description": "", "system_prompt": prompt, "model_id": model["id"]})
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
        if publish:
            assert client.post(f"/api/v1/agents/{r.json()['id']}/publish", headers=auth_headers).json()["publish_result"] == "published"
        return client.get(f"/api/v1/agents/{r.json()['id']}", headers=auth_headers).json()

    yield _make
    for aid in created:
        client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)


def _save(client, auth_headers, agent: dict, **changes):
    """PUT 整体覆盖草稿，带上最新的 expected_updated_at（乐观锁）。"""
    body = {k: agent[k] for k in ("name", "description", "system_prompt", "model_id", "params", "kb_ids", "tool_ids")}
    body.update(changes)
    body.setdefault("expected_updated_at", agent["updated_at"])
    return client.put(f"/api/v1/agents/{agent['id']}", headers=auth_headers, json=body)


def _versions(agent_id: int) -> list[int]:
    db = SessionLocal()
    try:
        return [v.version for v in db.query(AgentVersion).filter(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version)]
    finally:
        db.close()


def _live_prompt(client, headers, agent_id: int, monkeypatch) -> tuple[str, int]:
    """走一遍真实对话接口（模型用桩），返回这轮回答实际用的系统提示词与运行记录上的线上版本号。"""
    captured: list[str] = []
    use_llm(monkeypatch, AnswerModel(messages=iter(["好"])), captured)
    r = client.post(f"/api/v1/agents/{agent_id}/chat", headers=headers, json={"message": "你好"})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.agent_id == agent_id).order_by(Run.id.desc()).first()
        return captured[-1], run.agent_version
    finally:
        db.close()


def test_saving_draft_does_not_change_live_until_published(client, auth_headers, make_agent, monkeypatch):
    agent = make_agent("标记A")
    assert agent["published_version"] == 1 and agent["has_unpublished_changes"] is False
    saved = _save(client, auth_headers, agent, system_prompt="标记B")
    assert saved.status_code == 200, saved.text
    assert saved.json()["has_unpublished_changes"] is True and saved.json()["status"] == "published"
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-pub-key", "quota": 10, "agent_ids": [agent["id"]]}).json()
    try:
        for headers in (auth_headers, {"Authorization": "Bearer " + key["key"]}):  # JWT 与 API Key 都按线上版本回答
            prompt, version = _live_prompt(client, headers, agent["id"], monkeypatch)
            assert "标记A" in prompt and "标记B" not in prompt and version == 1
        published = client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers, json={"note": "改成 B"}).json()
        assert (published["publish_result"], published["published_version"]) == ("published", 2)
        prompt, version = _live_prompt(client, auth_headers, agent["id"], monkeypatch)
        assert "标记B" in prompt and version == 2
    finally:
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)


def test_publish_identical_draft_is_unchanged_and_idempotent(client, auth_headers, make_agent):
    agent = make_agent()
    again = client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).json()
    assert (again["publish_result"], again["published_version"]) == ("unchanged", 1)
    assert _versions(agent["id"]) == [1]


def test_concurrent_publish_creates_one_version(client, auth_headers, make_agent):
    agent = make_agent()
    _save(client, auth_headers, agent, system_prompt="并发发布")
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
    results: list = []

    def _publish():
        db = SessionLocal()
        try:
            results.append(agent_service.publish_agent(db, agent["id"], db.get(User, admin_id))["publish_result"])
        finally:
            db.close()

    threads = [threading.Thread(target=_publish) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["published", "unchanged"]  # 锁行后第二个看到的已是新线上版本
    assert _versions(agent["id"]) == [1, 2]


def test_restore_to_draft_keeps_live_and_rollback_to_live_keeps_draft(client, auth_headers, make_agent, monkeypatch):
    agent = make_agent("标记A")
    _save(client, auth_headers, agent, system_prompt="标记B")
    client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers)  # v2 = B
    versions = {v["version"]: v for v in client.get(f"/api/v1/agents/{agent['id']}/versions", headers=auth_headers).json()["items"]}
    assert versions[2]["is_live"] is True and versions[1]["is_live"] is False and versions[2]["created_by_username"] == "admin"
    # 恢复到草稿：草稿 = v1，线上仍是 v2
    restored = client.post(f"/api/v1/agents/{agent['id']}/versions/{versions[1]['id']}/restore", headers=auth_headers).json()
    assert restored["system_prompt"] == "标记A" and restored["published_version"] == 2 and restored["has_unpublished_changes"] is True
    assert "标记B" in _live_prompt(client, auth_headers, agent["id"], monkeypatch)[0]
    # 草稿再改成 C；回滚上线到 v1：线上 = A（新版本 v3），草稿仍是 C
    current = client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers).json()
    _save(client, auth_headers, current, system_prompt="标记C")
    rolled = client.post(f"/api/v1/agents/{agent['id']}/rollback/{versions[1]['id']}", headers=auth_headers).json()
    assert (rolled["publish_result"], rolled["published_version"], rolled["system_prompt"]) == ("published", 3, "标记C")
    assert "标记A" in _live_prompt(client, auth_headers, agent["id"], monkeypatch)[0]
    # 再回滚到与线上相同的快照：不生成新版本
    again = client.post(f"/api/v1/agents/{agent['id']}/rollback/{versions[1]['id']}", headers=auth_headers).json()
    assert (again["publish_result"], again["published_version"]) == ("unchanged", 3)
    db = SessionLocal()
    try:
        actions = {a.action for a in db.query(AuditLog).filter(AuditLog.resource == "agent", AuditLog.resource_id == agent["id"])}
    finally:
        db.close()
    assert {"publish", "update", "restore", "rollback"} <= actions


def test_detail_and_versions_give_snapshots_of_one_shape(client, auth_headers, make_agent):
    """发布弹窗与版本对比按后端给的快照做字段级差异，前端不维护字段清单：几份快照的键必须一致。"""
    never = make_agent(publish=False)
    assert never["live_snapshot"] is None and never["draft_snapshot"]["system_prompt"] == "标记A"
    agent = make_agent("标记A")
    _save(client, auth_headers, agent, system_prompt="标记B")
    detail = client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers).json()
    assert (detail["live_snapshot"]["system_prompt"], detail["draft_snapshot"]["system_prompt"]) == ("标记A", "标记B")
    assert set(detail["live_snapshot"]) == set(detail["draft_snapshot"])
    db = SessionLocal()
    try:  # 早期快照没有模板三字段
        db.add(AgentVersion(agent_id=agent["id"], version=99, snapshot={"name": "早期", "system_prompt": "旧", "model_id": agent["model_id"]}))
        db.commit()
    finally:
        db.close()
    items = client.get(f"/api/v1/agents/{agent['id']}/versions", headers=auth_headers).json()["items"]
    assert [v["version"] for v in items] == [99, 1] and all(set(v["snapshot"]) == set(detail["draft_snapshot"]) for v in items)


def test_offline_blocks_every_entry_and_publish_brings_back(client, auth_headers, make_agent, monkeypatch):
    agent = make_agent()
    r = client.post(f"/api/v1/agents/{agent['id']}/offline", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "offline"
    assert client.post(f"/api/v1/agents/{agent['id']}/offline", headers=auth_headers).status_code == 200  # 幂等
    db = SessionLocal()
    try:
        offline_audits = db.query(AuditLog).filter(AuditLog.resource == "agent", AuditLog.resource_id == agent["id"], AuditLog.action == "offline").count()
    finally:
        db.close()
    assert offline_audits == 1  # 重复下线不重复记审计
    use_llm(monkeypatch, AnswerModel(messages=iter(["不该回答"])))
    chat = client.post(f"/api/v1/agents/{agent['id']}/chat", headers=auth_headers, json={"message": "在吗"})
    assert chat.status_code == 403 and chat.json()["detail"] == "智能体已下线"
    names = [a["name"] for a in client.get("/api/v1/agents/available", headers=auth_headers, params={"q": agent["name"]}).json()["items"]]
    assert names == []
    back = client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).json()
    assert back["status"] == "published" and back["published_version"] == 1  # 草稿没变：重新上线不生成新版本


def test_draft_agent_cannot_be_taken_offline_or_chatted(client, auth_headers, make_agent):
    agent = make_agent(publish=False)
    r = client.post(f"/api/v1/agents/{agent['id']}/offline", headers=auth_headers)
    assert r.status_code == 400
    chat = client.post(f"/api/v1/agents/{agent['id']}/chat", headers=auth_headers, json={"message": "在吗"})
    assert chat.status_code == 403 and chat.json()["detail"] == "智能体未发布"


def test_available_list_reads_live_snapshot_not_draft(client, auth_headers, make_agent):
    agent = make_agent()
    _save(client, auth_headers, agent, name=agent["name"] + "-草稿改名", description="草稿描述")
    items = client.get("/api/v1/agents/available", headers=auth_headers, params={"q": agent["name"]}).json()["items"]
    mine = [i for i in items if i["id"] == agent["id"]]
    assert len(mine) == 1 and mine[0]["name"] == agent["name"] and mine[0]["description"] == ""
    assert set(mine[0]) == {"id", "name", "description", "published_at"}  # 不暴露草稿的编辑时间


def test_workflow_agent_node_refuses_unpublished_agent(client, auth_headers, make_agent):
    agent = make_agent(publish=False)
    graph = {"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "a", "type": "agent", "config": {"agent_id": agent["id"]}}, {"id": "e", "type": "end", "config": {}}],
             "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "e"}]}
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-pub-wf", "description": "", "graph": graph}).json()
    try:
        r = client.post(f"/api/v1/workflows/{wf['id']}/run", headers=auth_headers, json={"input": "hi"}).json()
        assert r["status"] == "failed" and "智能体未发布" in r["error"]
    finally:
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)


def test_publish_refuses_disabled_model_without_new_version(client, auth_headers, make_agent, model):
    agent = make_agent()
    _save(client, auth_headers, agent, system_prompt="改过")
    assert client.post(f"/api/v1/models/{model['id']}/toggle", headers=auth_headers).json()["is_enabled"] is False
    try:
        r = client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers)
        assert r.status_code == 400 and r.json()["detail"] == "模型已停用"
        assert _versions(agent["id"]) == [1]
    finally:
        client.post(f"/api/v1/models/{model['id']}/toggle", headers=auth_headers)


def test_delete_model_refused_while_live_version_still_uses_it(client, auth_headers, make_agent, model, monkeypatch):
    agent = make_agent("标记A")
    other = _new_model(client, auth_headers)
    try:
        assert _save(client, auth_headers, agent, model_id=other["id"]).status_code == 200  # 草稿换了模型，线上仍用 model
        r = client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers)
        assert r.status_code == 409 and "线上版本" in r.json()["detail"]
        detail = client.get(f"/api/v1/models/{model['id']}", headers=auth_headers).json()  # 详情的"引用它的智能体"同一口径
        assert [a["id"] for a in detail["agents"]] == [agent["id"]] and detail["agents_count"] == 1
        listed = client.get("/api/v1/agents", headers=auth_headers, params={"model_id": model["id"]}).json()  # 引用数链接到的列表
        assert [a["id"] for a in listed["items"]] == [agent["id"]]
        prompt, version = _live_prompt(client, auth_headers, agent["id"], monkeypatch)  # 线上照常回答
        assert "标记A" in prompt and version == 1
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{other['id']}", headers=auth_headers)


def test_delete_model_allowed_when_only_old_versions_use_it(client, auth_headers, make_agent, model):
    agent = make_agent()
    other = _new_model(client, auth_headers)
    try:
        _save(client, auth_headers, agent, model_id=other["id"])
        assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).json()["published_version"] == 2
        # 只剩 v1 这个历史版本引用它：回滚上线到 v1 时会按 404「模型不存在」拦下，不会悬空，所以不拦删除
        assert client.delete(f"/api/v1/models/{model['id']}", headers=auth_headers).status_code == 200
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{other['id']}", headers=auth_headers)


@pytest.mark.parametrize("changes,status,detail", [
    ({"model_id": 999999999}, 404, "模型不存在"),
    ({"kb_ids": [999999999]}, 400, "知识库不存在：999999999"),
    ({"tool_ids": [999999998, 999999999]}, 400, "工具不存在：999999998, 999999999"),
])
def test_save_validates_references(client, auth_headers, make_agent, changes, status, detail):
    agent = make_agent(publish=False)
    r = _save(client, auth_headers, agent, **changes)
    assert r.status_code == status and r.json()["detail"] == detail


@pytest.mark.parametrize("changes", [{"name": "字" * 129}, {"kb_ids": ["abc"]}, {"tool_ids": list(range(1, 22))}, {"name": ""}])
def test_save_rejects_malformed_fields_with_422(client, auth_headers, make_agent, changes):
    agent = make_agent(publish=False)
    assert _save(client, auth_headers, agent, **changes).status_code == 422


def test_stale_expected_updated_at_is_409_and_not_saved(client, auth_headers, make_agent):
    agent = make_agent(publish=False)
    assert _save(client, auth_headers, agent, system_prompt="先保存一次").status_code == 200
    stale = _save(client, auth_headers, agent, system_prompt="拿旧版本覆盖")  # 还带着第一次读到的 updated_at
    assert stale.status_code == 409 and "已被他人修改" in stale.json()["detail"]
    assert client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers).json()["system_prompt"] == "先保存一次"


def test_foreign_version_id_is_404_for_restore_and_rollback(client, auth_headers, make_agent):
    a, b = make_agent(), make_agent()
    foreign = client.get(f"/api/v1/agents/{b['id']}/versions", headers=auth_headers).json()["items"][0]["id"]
    assert client.post(f"/api/v1/agents/{a['id']}/versions/{foreign}/restore", headers=auth_headers).status_code == 404
    assert client.post(f"/api/v1/agents/{a['id']}/rollback/{foreign}", headers=auth_headers).status_code == 404


def test_prepare_chat_records_live_version_and_model(client, auth_headers, make_agent):
    agent = make_agent()
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
    db = SessionLocal()
    try:
        prepared = chat_service.prepare_chat(db, conversation_service.Caller("ui", admin_id), agent["id"], "你好")
        run = db.get(Run, prepared.run_id)
        assert (run.agent_version, run.model_id, run.source) == (1, agent["model_id"], "chat")
    finally:
        db.close()
