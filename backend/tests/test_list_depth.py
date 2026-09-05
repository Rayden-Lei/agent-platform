"""列表深化（页面深度优化后端第 0 批）：各列表的筛选 / 排序 / 关联字段、启停开关、批量接口、定时任务编辑、密码重置。"""
import uuid

import pytest

from app.db.models import Conversation, Message
from app.db.session import SessionLocal
from app.tools.langchain_tools import build_tools


def _model(client, auth_headers, **extra) -> dict:
    return client.post("/api/v1/models", headers=auth_headers, json={"name": "pytest-depth-model-" + uuid.uuid4().hex[:6], "provider": "openai", "api_base": "http://upstream.test/v1", "api_key": "sk", "model_name": "x", "default_params": {}, **extra}).json()


def _tool(client, auth_headers, name: str) -> dict:
    r = client.post("/api/v1/tools", headers=auth_headers, json={"name": name, "description": "x", "type": "http", "config": {"url": "http://upstream.test/x", "method": "GET"}, "timeout": 5})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 批量接口的通用约束 ----------

def test_batch_rejects_empty_ids_unknown_action_and_too_many(client, auth_headers):
    assert client.post("/api/v1/tools/batch", headers=auth_headers, json={"ids": [], "action": "delete"}).status_code == 422
    assert client.post("/api/v1/tools/batch", headers=auth_headers, json={"ids": [1], "action": "toggle"}).status_code == 422
    assert client.post("/api/v1/tools/batch", headers=auth_headers, json={"ids": list(range(1, 102)), "action": "delete"}).status_code == 422


def test_batch_reports_per_item_failure_and_continues(client, auth_headers):
    a = _tool(client, auth_headers, "pytest-batch-a-" + uuid.uuid4().hex[:4])
    b = _tool(client, auth_headers, "pytest-batch-b-" + uuid.uuid4().hex[:4])
    r = client.post("/api/v1/tools/batch", headers=auth_headers, json={"ids": [a["id"], 999999999, b["id"], a["id"]], "action": "disable"})
    assert r.status_code == 200, r.text
    assert r.json()["succeeded"] == [a["id"], b["id"]]  # 去重后按顺序
    assert r.json()["failed"] == [{"id": 999999999, "detail": "工具不存在"}]
    listed = client.get("/api/v1/tools", headers=auth_headers, params={"is_enabled": "false", "q": "pytest-batch-"}).json()
    assert {t["id"] for t in listed["items"]} >= {a["id"], b["id"]}
    deleted = client.post("/api/v1/tools/batch", headers=auth_headers, json={"ids": [a["id"], b["id"]], "action": "delete"}).json()
    assert deleted["failed"] == [] and set(deleted["succeeded"]) == {a["id"], b["id"]}


# ---------- 工具：启停 ----------

def test_disabled_tool_is_not_exposed_to_model_and_fails_workflow_node(client, auth_headers):
    t = _tool(client, auth_headers, "pytest_toggle_tool_" + uuid.uuid4().hex[:4])
    try:
        r = client.post(f"/api/v1/tools/{t['id']}/toggle", headers=auth_headers)
        assert r.json() == {"id": t["id"], "is_enabled": False}
        from app.db.models import Tool
        db = SessionLocal()
        try:
            assert [x.name for x in build_tools([db.get(Tool, t["id"])])] == ["current_time", "calculator"]
        finally:
            db.close()
        detail = client.get(f"/api/v1/tools/{t['id']}", headers=auth_headers).json()
        assert detail["is_enabled"] is False and detail["agents"] == []
        graph = {"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "t", "type": "tool", "config": {"tool_name": t["name"], "args": {}}}, {"id": "e", "type": "end", "config": {}}],
                 "edges": [{"from": "s", "to": "t"}, {"from": "t", "to": "e"}]}
        run = client.post("/api/v1/workflows/test-run", headers=auth_headers, json={"graph": graph, "input": "x"}).json()
        assert run["status"] == "failed" and "工具已停用" in run["error"]
        assert client.post(f"/api/v1/tools/{t['id']}/toggle", headers=auth_headers).json()["is_enabled"] is True
    finally:
        client.delete(f"/api/v1/tools/{t['id']}", headers=auth_headers)


# ---------- 模型：启停、筛选、引用计数 ----------

def test_models_toggle_filters_and_agents_count(client, auth_headers):
    m = _model(client, auth_headers)
    agent = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-depth-agent-" + uuid.uuid4().hex[:4], "description": "", "system_prompt": "x", "model_id": m["id"]}).json()
    try:
        listed = client.get("/api/v1/models", headers=auth_headers, params={"q": m["name"]}).json()["items"][0]
        assert listed["agents_count"] == 1 and listed["created_by_username"] == "admin" and listed["created_at"]
        assert client.post(f"/api/v1/models/{m['id']}/toggle", headers=auth_headers).json()["is_enabled"] is False
        assert client.get("/api/v1/models", headers=auth_headers, params={"q": m["name"], "is_enabled": "true"}).json()["total"] == 0
        assert client.get("/api/v1/models", headers=auth_headers, params={"q": m["name"], "is_enabled": "false"}).json()["total"] == 1
        detail = client.get(f"/api/v1/models/{m['id']}", headers=auth_headers).json()
        assert detail["agents"] == [{"id": agent["id"], "name": agent["name"], "status": "draft"}]
        batch = client.post("/api/v1/models/batch", headers=auth_headers, json={"ids": [m["id"]], "action": "delete"}).json()
        assert batch["failed"][0]["detail"].startswith("该模型已被 1 个智能体引用")
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{m['id']}", headers=auth_headers)


# ---------- 智能体：筛选、关联字段、详情悬空引用 ----------

def test_agents_list_filters_and_detail_reports_missing_references(client, auth_headers):
    m = _model(client, auth_headers)
    t = _tool(client, auth_headers, "pytest-depth-tool-" + uuid.uuid4().hex[:4])
    agent = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-depth-agent-" + uuid.uuid4().hex[:4], "description": "", "system_prompt": "x", "model_id": m["id"], "tool_ids": [t["id"], 999999999], "kb_ids": [999999998]}).json()
    try:
        by_model = client.get("/api/v1/agents", headers=auth_headers, params={"model_id": m["id"]}).json()
        assert [a["id"] for a in by_model["items"]] == [agent["id"]] and by_model["items"][0]["model_name"] == m["name"]
        assert by_model["items"][0]["created_by_username"] == "admin" and by_model["items"][0]["runs_7d"] == 0
        assert client.get("/api/v1/agents", headers=auth_headers, params={"tool_id": t["id"]}).json()["total"] == 1
        assert client.get("/api/v1/agents", headers=auth_headers, params={"tool_id": 999999997}).json()["total"] == 0
        assert client.get("/api/v1/agents", headers=auth_headers, params={"sort": "nope"}).status_code == 400
        detail = client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers).json()
        assert detail["model"]["name"] == m["name"] and detail["tools"] == [{"id": t["id"], "name": t["name"], "type": "http", "is_enabled": True}]
        assert detail["missing_tool_ids"] == [999999999] and detail["missing_kb_ids"] == [999999998] and detail["knowledge_bases"] == []
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/tools/{t['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{m['id']}", headers=auth_headers)


# ---------- 定时任务：cron 校验、编辑、下次触发、批量 ----------

def test_schedules_validate_cron_and_expose_next_run(client, auth_headers):
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-depth-wf-" + uuid.uuid4().hex[:4], "description": "", "graph": {"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "e", "type": "end", "config": {}}], "edges": [{"from": "s", "to": "e"}]}}).json()
    try:
        bad = client.post("/api/v1/schedules", headers=auth_headers, json={"name": "pytest-sched", "workflow_id": wf["id"], "cron": "every 5 minutes", "input": {}})
        assert bad.status_code == 422 and "cron 表达式非法" in bad.json()["detail"][0]["msg"]
        missing = client.post("/api/v1/schedules", headers=auth_headers, json={"name": "pytest-sched", "workflow_id": 999999999, "cron": "0 3 * * *", "input": {}})
        assert missing.status_code == 404
        created = client.post("/api/v1/schedules", headers=auth_headers, json={"name": "pytest-sched-" + uuid.uuid4().hex[:4], "workflow_id": wf["id"], "cron": "0 3 * * *", "input": {"input": "x"}})
        assert created.status_code == 200, created.text
        sched = created.json()
        try:
            assert sched["workflow_name"] == wf["name"] and sched["username"] == "admin" and sched["cron_valid"] is True
            assert sched["next_run_at"] is not None and sched["input"] == {"input": "x"}
            updated = client.put(f"/api/v1/schedules/{sched['id']}", headers=auth_headers, json={"name": sched["name"], "workflow_id": wf["id"], "cron": "30 4 * * *", "input": {"input": "y"}}).json()
            assert updated["cron"] == "30 4 * * *" and updated["next_run_at"] != sched["next_run_at"] and updated["input"] == {"input": "y"}
            off = client.post("/api/v1/schedules/batch", headers=auth_headers, json={"ids": [sched["id"]], "action": "disable"}).json()
            assert off["succeeded"] == [sched["id"]]
            listed = client.get("/api/v1/schedules", headers=auth_headers, params={"workflow_id": wf["id"], "is_enabled": "false"}).json()["items"][0]
            assert listed["is_enabled"] is False and listed["next_run_at"] is None
        finally:
            client.delete(f"/api/v1/schedules/{sched['id']}", headers=auth_headers)
    finally:
        client.delete(f"/api/v1/workflows/{wf['id']}", headers=auth_headers)


# ---------- 用户：筛选、自我保护、重置密码 ----------

def test_users_cannot_disable_self_and_reset_password_works(client, auth_headers):
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()
    assert client.put(f"/api/v1/users/{me['id']}", headers=auth_headers, json={"is_active": False}).status_code == 400
    batch = client.post("/api/v1/users/batch", headers=auth_headers, json={"ids": [me["id"]], "action": "disable"}).json()
    assert batch["succeeded"] == [] and "当前登录" in batch["failed"][0]["detail"]
    username = "pytest-reset-" + uuid.uuid4().hex[:6]
    created = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "old-pass-1", "role": "caller"}).json()
    try:
        assert created["created_at"]
        assert client.get("/api/v1/users", headers=auth_headers, params={"role": "caller", "q": username}).json()["total"] == 1
        assert client.post(f"/api/v1/users/{created['id']}/reset-password", headers=auth_headers, json={"password": "12"}).status_code == 422
        assert client.post(f"/api/v1/users/{created['id']}/reset-password", headers=auth_headers, json={"password": "new-pass-1"}).status_code == 200
        assert client.post("/api/v1/auth/login", json={"username": username, "password": "new-pass-1"}).status_code == 200
        audit = client.get("/api/v1/audit-logs", headers=auth_headers, params={"action": "reset_password", "resource_id": created["id"]}).json()
        assert audit["total"] >= 1 and audit["items"][0]["detail"] == {"username": username}
    finally:
        client.delete(f"/api/v1/users/{created['id']}", headers=auth_headers)


# ---------- 审计：时间区间、资源 ID ----------

def test_audit_logs_filters_and_time_range_validation(client, auth_headers):
    assert client.get("/api/v1/audit-logs", headers=auth_headers, params={"created_from": "2026-09-01T00:00:00"}).status_code == 400
    r = client.get("/api/v1/audit-logs", headers=auth_headers, params={"created_from": "2020-01-01T00:00:00+08:00", "created_to": "2020-01-02T00:00:00+08:00"})
    assert r.status_code == 200 and r.json()["total"] == 0
    latest = client.get("/api/v1/audit-logs", headers=auth_headers, params={"sort": "created_at", "order": "desc", "page_size": 1}).json()
    assert latest["items"] and "user_id" in latest["items"][0]


# ---------- API Key：创建人与筛选 ----------

def test_api_keys_list_has_username_and_filters(client, auth_headers):
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-depth-key-" + uuid.uuid4().hex[:4], "quota": 5}).json()
    try:
        listed = client.get("/api/v1/api-keys", headers=auth_headers, params={"q": key["name"]}).json()["items"][0]
        assert listed["username"] == "admin" and listed["user_id"] == key["user_id"]
        client.post(f"/api/v1/api-keys/{key['id']}/toggle", headers=auth_headers)
        assert client.get("/api/v1/api-keys", headers=auth_headers, params={"q": key["name"], "is_enabled": "true"}).json()["total"] == 0
        batch = client.post("/api/v1/api-keys/batch", headers=auth_headers, json={"ids": [key["id"], 999999999], "action": "enable"}).json()
        assert batch["succeeded"] == [key["id"]] and batch["failed"][0]["detail"] == "API Key 不存在"
    finally:
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)


# ---------- 知识库：统计字段与文档筛选 ----------

def test_kb_list_has_stats_and_document_list_validates_sort(client, auth_headers):
    kb = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": "pytest-depth-kb-" + uuid.uuid4().hex[:4], "description": ""}).json()
    try:
        assert kb["document_count"] == 0 and kb["embedding_model"] and kb["created_by_username"] == "admin"
        listed = client.get("/api/v1/knowledge-bases", headers=auth_headers, params={"q": kb["name"], "is_public": "true"}).json()["items"][0]
        assert listed["chunk_count"] == 0 and listed["policy_version"] == 1
        detail = client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers).json()
        assert detail["agents"] == [] and detail["failed_count"] == 0
        assert client.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=auth_headers, params={"sort": "size"}).status_code == 400
        assert client.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=auth_headers, params={"status": "failed", "q": "x"}).json()["total"] == 0
        assert client.post(f"/api/v1/knowledge-bases/{kb['id']}/documents/999999999/reprocess", headers=auth_headers).status_code == 404
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)


# ---------- 模板：绑定数与批量删除 409 ----------

def test_prompt_templates_list_agents_count_and_batch_delete_reports_409(client, auth_headers):
    tpl = client.post("/api/v1/prompt-templates", headers=auth_headers, json={"name": "pytest-depth-tpl-" + uuid.uuid4().hex[:6], "content": "你是{{role}}", "variables": [{"name": "role", "required": True}]}).json()
    m = _model(client, auth_headers)
    agent = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-depth-tpl-agent", "description": "", "model_id": m["id"], "prompt_template_id": tpl["id"], "prompt_variables": {"role": "客服"}}).json()
    try:
        listed = client.get("/api/v1/prompt-templates", headers=auth_headers, params={"q": tpl["name"]}).json()["items"][0]
        assert listed["agents_count"] == 1 and listed["created_by_username"] == "admin"
        bound = client.get(f"/api/v1/prompt-templates/{tpl['id']}/agents", headers=auth_headers).json()
        assert bound == [{"id": agent["id"], "name": agent["name"], "status": "draft", "prompt_template_version": 1, "outdated": False}]
        batch = client.post("/api/v1/prompt-templates/batch", headers=auth_headers, json={"ids": [tpl["id"]], "action": "delete"}).json()
        assert batch["failed"] == [{"id": tpl["id"], "detail": "仍有 1 个智能体绑定该模板"}]
    finally:
        client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        client.delete(f"/api/v1/prompt-templates/{tpl['id']}", headers=auth_headers)
        client.delete(f"/api/v1/models/{m['id']}", headers=auth_headers)


# ---------- 工作流：节点统计、复制、批量 ----------

def test_workflows_list_node_count_duplicate_and_batch_delete(client, auth_headers):
    graph = {"nodes": [{"id": "s", "type": "start", "config": {}}, {"id": "c", "type": "code", "config": {"code": "result=1"}}, {"id": "e", "type": "end", "config": {}}], "edges": [{"from": "s", "to": "c"}, {"from": "c", "to": "e"}]}
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-depth-wf-" + uuid.uuid4().hex[:4], "description": "d", "graph": graph}).json()
    copy = client.post(f"/api/v1/workflows/{wf['id']}/duplicate", headers=auth_headers).json()
    try:
        listed = client.get("/api/v1/workflows", headers=auth_headers, params={"q": wf["name"], "status": "draft"}).json()
        assert listed["total"] == 2
        item = next(i for i in listed["items"] if i["id"] == wf["id"])
        assert item["node_count"] == 3 and item["node_types"] == {"start": 1, "code": 1, "end": 1} and item["schedules_count"] == 0
        assert copy["name"] == wf["name"] + " 副本" and copy["version"] == 1
        detail = client.get(f"/api/v1/workflows/{wf['id']}", headers=auth_headers).json()
        assert detail["graph"] == graph and detail["agents"] == [] and detail["schedules"] == []
    finally:
        batch = client.post("/api/v1/workflows/batch", headers=auth_headers, json={"ids": [wf["id"], copy["id"]], "action": "delete"}).json()
        assert batch["failed"] == []


# ---------- 会话与消息 ----------

def test_conversations_carry_message_count_and_messages_carry_token_usage(client, auth_headers):
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
    db = SessionLocal()
    try:
        conv = Conversation(user_id=me, title="pytest-depth-conv")
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conv_id = conv.id
        db.add(Message(conversation_id=conv_id, role="user", content="q"))
        db.add(Message(conversation_id=conv_id, role="assistant", content="a", token_usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}))
        db.commit()
    finally:
        db.close()
    try:
        listed = client.get("/api/v1/conversations", headers=auth_headers, params={"q": "pytest-depth-conv"}).json()["items"][0]
        assert listed["message_count"] == 2 and listed["agent_name"] is None
        messages = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=auth_headers).json()
        assert messages[0]["token_usage"] is None and messages[1]["token_usage"] == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    finally:
        client.delete(f"/api/v1/conversations/{conv_id}", headers=auth_headers)
