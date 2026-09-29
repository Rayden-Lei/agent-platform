"""装配页当场调试（docs/15 3.4，FR-041；AC-022 的后端部分）与执行器的多轮用量。

模型一律换成桩（monkeypatch chat_service.build_llm），不发网络请求；其余链路（配置解析、校验、检索装配、执行器、运行记录）走真实代码。
"""
import json
import uuid

import pytest

from app.db.models import Conversation, Run
from app.db.session import SessionLocal
from app.services import chat_service
from tests.fakes import AnswerModel, ScriptedModel


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def model(client, auth_headers):
    r = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-debug-model-" + _uid(), "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {}, "price_input": 1, "price_output": 2,
    })
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"/api/v1/models/{r.json()['id']}", headers=auth_headers)


@pytest.fixture
def agent(client, auth_headers, model):
    """从未发布的草稿，提示词"标记A"。"""
    r = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-debug-" + _uid(), "description": "", "system_prompt": "标记A", "model_id": model["id"]})
    assert r.status_code == 200, r.text
    yield client.get(f"/api/v1/agents/{r.json()['id']}", headers=auth_headers).json()
    client.delete(f"/api/v1/agents/{r.json()['id']}", headers=auth_headers)


def _stub(monkeypatch, make) -> None:
    """每次构建上下文都换一个新桩（桩的回答迭代器用一次就空了）。"""
    monkeypatch.setattr(chat_service, "build_llm", lambda model, params=None: make())


def _events(resp) -> list[dict]:
    return [json.loads(part[6:]) for part in resp.text.split("\n\n") if part.startswith("data: ")]


def _inline(agent: dict, **changes) -> dict:
    config = {k: agent[k] for k in ("name", "description", "system_prompt", "model_id", "params", "kb_ids", "tool_ids")}
    return {**config, **changes}


def _debug(client, headers, agent_id: int, **body):
    return client.post(f"/api/v1/agents/{agent_id}/debug-chat", headers=headers, json={"message": "你好", **body})


def _debug_run_count(agent_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.agent_id == agent_id, Run.source == "debug").count()
    finally:
        db.close()


def _run(run_id: int) -> dict:
    db = SessionLocal()
    try:
        r = db.get(Run, run_id)
        return {"source": r.source, "conversation_id": r.conversation_id, "agent_version": r.agent_version, "status": r.status, "token_usage": r.token_usage, "cost": r.cost}
    finally:
        db.close()


def test_inline_debug_answers_with_unsaved_config_and_writes_nothing_else(client, auth_headers, agent, monkeypatch):
    _stub(monkeypatch, lambda: AnswerModel(messages=iter(["调试回答"])))
    history = [{"role": "user", "content": "上一问"}, {"role": "assistant", "content": "上一答"}]
    r = _debug(client, auth_headers, agent["id"], history=history, config_source="inline", config=_inline(agent, system_prompt="标记B"))
    assert r.status_code == 200, r.text
    events = _events(r)
    prompt = next(e for e in events if e["type"] == "prompt")
    assert "标记B" in prompt["system_prompt"] and "标记A" not in prompt["system_prompt"] and prompt["history_count"] == 2
    assert "".join(e["content"] for e in events if e["type"] == "delta") == "调试回答"
    done = events[-1]
    assert done["type"] == "done" and "conversation_id" not in done and "message_id" not in done
    assert done["metrics"]["config_source"] == "inline" and done["metrics"]["model_id"] == agent["model_id"]
    run = _run(done["run_id"])
    assert (run["source"], run["conversation_id"], run["agent_version"], run["status"]) == ("debug", None, None, "success")
    after = client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers).json()
    assert after["updated_at"] == agent["updated_at"] and after["system_prompt"] == "标记A"  # 不写 agents 行
    db = SessionLocal()
    try:
        assert db.query(Conversation).filter(Conversation.agent_id == agent["id"]).count() == 0  # 不建会话、不落消息
    finally:
        db.close()


def test_draft_and_live_sources_each_use_their_own_config(client, auth_headers, agent, monkeypatch):
    _stub(monkeypatch, lambda: AnswerModel(messages=iter(["好"])))
    never = _debug(client, auth_headers, agent["id"], config_source="live")
    assert never.status_code == 400 and "还没有发布过" in never.json()["detail"]
    assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).status_code == 200  # v1 = 标记A
    current = client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers).json()
    body = {**_inline(current, system_prompt="标记C"), "expected_updated_at": current["updated_at"]}
    assert client.put(f"/api/v1/agents/{agent['id']}", headers=auth_headers, json=body).status_code == 200
    live, draft = (_events(_debug(client, auth_headers, agent["id"], config_source=s)) for s in ("live", "draft"))
    assert "标记A" in next(e for e in live if e["type"] == "prompt")["system_prompt"]
    assert "标记C" in next(e for e in draft if e["type"] == "prompt")["system_prompt"]
    assert _run(live[-1]["run_id"])["agent_version"] == 1 and _run(draft[-1]["run_id"])["agent_version"] is None


def test_debug_trace_has_a_step_per_model_call_and_tool(client, auth_headers, agent, monkeypatch):
    _stub(monkeypatch, lambda: ScriptedModel(script=[("tool", "current_time"), ("tool", "current_time"), ("text", "好了")]))
    events = _events(_debug(client, auth_headers, agent["id"], config=_inline(agent)))
    steps = [e["step"] for e in events if e["type"] == "trace"]
    assert [s["type"] for s in steps] == ["llm", "tool", "llm", "tool", "llm"]
    assert [s["meta"]["usage"]["prompt_tokens"] for s in steps if s["type"] == "llm"] == [10, 20, 30]
    assert all(s["status"] == "success" and s["input"] == {} and s["output"] for s in steps if s["type"] == "tool")
    done = events[-1]
    assert done["usage"] == {"prompt_tokens": 60, "completion_tokens": 6, "total_tokens": 66}
    run = _run(done["run_id"])
    assert run["token_usage"] == done["usage"] and done["metrics"]["cost"] == run["cost"] and run["cost"] > 0


def test_online_chat_adds_up_usage_and_keeps_tool_args_across_rounds(client, auth_headers, agent, monkeypatch):
    """2026-09-29 前：用量只剩最后一次模型调用的；第二轮起的工具参数拼在第一轮后面，tool_call 事件显示成 _raw。"""
    assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).status_code == 200
    _stub(monkeypatch, lambda: ScriptedModel(script=[("tool", "current_time"), ("tool", "current_time"), ("text", "好了")]))
    events = _events(client.post(f"/api/v1/agents/{agent['id']}/chat", headers=auth_headers, json={"message": "几点了"}))
    assert [e["arguments"] for e in events if e["type"] == "tool_call"] == [{}, {}]
    done = events[-1]
    assert done["type"] == "done" and done["usage"] == {"prompt_tokens": 60, "completion_tokens": 6, "total_tokens": 66}
    assert _run(done["run_id"])["token_usage"] == done["usage"]


def test_debug_retrieve_step_lists_hits_without_content(client, auth_headers, agent, monkeypatch):
    kb = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": "pytest-debug-kb-" + _uid(), "description": "", "embedding_model": "embedding-3", "chunk_size": 200, "chunk_overlap": 20,
    }).json()
    canned = {"items": [{"content": "片段正文", "score": 0.9, "chunk_id": 9, "doc_id": 3, "doc_name": "说明书.pdf", "meta": {"type": "pdf", "page": 3, "kb_id": 1},
                         "rerank_score": 0.8, "vector_score": 0.7, "keyword_score": 0.5}],
              "stats": {"candidate_count": 5, "returned": 1, "acl_rejected": 0, "kb_denied": False, "rerank_mode": "lexical", "timings": {"embed_ms": 1}}}
    monkeypatch.setattr(chat_service, "retrieve_with_stats", lambda kb_id, query, top_k=None, mode="hybrid", role=None: canned)
    _stub(monkeypatch, lambda: AnswerModel(messages=iter(["依据片段回答"])))
    try:
        events = _events(_debug(client, auth_headers, agent["id"], config=_inline(agent, kb_ids=[kb["id"]])))
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
    step = next(e["step"] for e in events if e["type"] == "trace" and e["step"]["type"] == "retrieve")
    assert step["name"] == kb["name"] and step["input"] == {"query": "你好"} and step["meta"]["candidate_count"] == 5
    assert step["output"] == [{"chunk_id": 9, "doc_id": 3, "doc_name": "说明书.pdf", "score": 0.9, "vector_score": 0.7, "keyword_score": 0.5,
                               "rerank_score": 0.8, "location": {"type": "pdf", "page": 3}}]  # 不重复带正文
    assert next(e for e in events if e["type"] == "citations")["citations"][0]["content"] == "片段正文"


@pytest.mark.parametrize("changes,status,detail", [
    ({"model_id": 999999999}, 404, "模型不存在"),
    ({"tool_ids": [999999999]}, 400, "工具不存在：999999999"),
    ({"kb_ids": [999999998]}, 400, "知识库不存在：999999998"),
])
def test_bad_inline_config_is_rejected_before_any_run(client, auth_headers, agent, changes, status, detail):
    r = _debug(client, auth_headers, agent["id"], config=_inline(agent, **changes))
    assert r.status_code == status and r.json()["detail"] == detail
    assert _debug_run_count(agent["id"]) == 0


def test_disabled_model_is_rejected_before_any_run(client, auth_headers, agent, model):
    assert client.post(f"/api/v1/models/{model['id']}/toggle", headers=auth_headers).json()["is_enabled"] is False
    try:
        r = _debug(client, auth_headers, agent["id"], config=_inline(agent))
        assert r.status_code == 400 and r.json()["detail"] == "模型已停用"
        assert _debug_run_count(agent["id"]) == 0
    finally:
        client.post(f"/api/v1/models/{model['id']}/toggle", headers=auth_headers)


@pytest.mark.parametrize("body", [
    {"history": [{"role": "user", "content": "x"}] * 41},
    {"history": [{"role": "user", "content": "字" * 32001}, {"role": "assistant", "content": "字" * 32000}]},
    {"history": [{"role": "system", "content": "越权"}]},
    {"message": ""},
    {"config_source": "inline"},
    {"config_source": "draft", "config": {"name": "x", "model_id": 1}},
])
def test_malformed_debug_request_is_422(client, auth_headers, agent, body):
    assert _debug(client, auth_headers, agent["id"], **body).status_code == 422
    assert _debug_run_count(agent["id"]) == 0


def test_debug_is_for_admin_and_developer_jwt_only(client, auth_headers, caller_headers, agent):
    assert _debug(client, caller_headers, agent["id"], config=_inline(agent)).status_code == 403
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-debug-key", "quota": 10}).json()
    try:
        assert _debug(client, {"Authorization": "Bearer " + key["key"]}, agent["id"], config=_inline(agent)).status_code == 403
    finally:
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)
    assert _debug(client, auth_headers, 999999999, config=_inline(agent)).status_code == 404


def test_debug_runs_stay_out_of_operational_metrics_but_count_for_the_model(client, auth_headers, agent, model, monkeypatch):
    _stub(monkeypatch, lambda: AnswerModel(messages=iter(["好"])))
    run_id = _events(_debug(client, auth_headers, agent["id"], config=_inline(agent)))[-1]["run_id"]
    by_agent = client.get("/api/v1/stats/agents", headers=auth_headers, params={"agent_id": agent["id"], "days": 1}).json()["items"]
    assert by_agent[0]["total"] == 0
    listed = client.get("/api/v1/agents", headers=auth_headers, params={"q": agent["name"]}).json()["items"]
    assert listed[0]["runs_7d"] == 0
    assert client.get("/api/v1/stats/runs/daily", headers=auth_headers, params={"agent_id": agent["id"], "days": 1}).json()["items"][-1]["total"] == 0
    assert run_id not in [r["id"] for r in client.get("/api/v1/stats/overview", headers=auth_headers).json()["recent_runs"]]
    by_model = client.get("/api/v1/stats/models", headers=auth_headers, params={"model_id": model["id"], "days": 1}).json()["items"]
    assert by_model[0]["total"] == 1  # 调试花的钱计入模型消耗
    runs = client.get("/api/v1/runs", headers=auth_headers, params={"agent_id": agent["id"], "source": "debug"}).json()["items"]
    assert [r["id"] for r in runs] == [run_id]  # 运行记录页能按来源筛出
