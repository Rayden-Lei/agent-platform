def _make_model(client, auth_headers):
    res = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-agent-model", "provider": "openai", "api_base": "https://example.com/v1",
        "api_key": "sk-test", "model_name": "m", "default_params": {},
    })
    return res.json()["id"]


def test_agent_crud_publish_rollback(client, auth_headers):
    model_id = _make_model(client, auth_headers)

    a = client.post("/api/v1/agents", headers=auth_headers, json={
        "name": "pytest-agent", "description": "", "system_prompt": "你是测试助手",
        "model_id": model_id, "params": {}, "kb_ids": [], "tool_ids": [], "workflow_id": None,
    })
    assert a.status_code == 200, a.text
    aid = a.json()["id"]
    assert a.json()["status"] == "draft"

    p = client.post(f"/api/v1/agents/{aid}/publish", headers=auth_headers)
    assert p.status_code == 200
    assert p.json()["status"] == "published"

    v = client.get(f"/api/v1/agents/{aid}/versions", headers=auth_headers)
    assert v.status_code == 200
    versions = v.json()["items"]
    assert len(versions) >= 1

    rb = client.post(f"/api/v1/agents/{aid}/rollback/{versions[0]['id']}", headers=auth_headers)
    assert rb.status_code == 200

    d = client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)
    assert d.status_code == 200
    client.delete(f"/api/v1/models/{model_id}", headers=auth_headers)


# ---------- 智能体绑定 Prompt 模板（`12-差距补齐开发计划.md` 2.8，FR-028） ----------

import uuid  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import event  # noqa: E402

from app.db.session import engine  # noqa: E402

TPL_CONTENT = "你是{{role}}，语气{{tone}}。"
TPL_VARS = [{"name": "role", "required": True}, {"name": "tone", "default": "友好"}]


@pytest.fixture
def model_id(client, auth_headers):
    mid = _make_model(client, auth_headers)
    yield mid
    client.delete(f"/api/v1/models/{mid}", headers=auth_headers)


@pytest.fixture
def template(client, auth_headers):
    r = client.post("/api/v1/prompt-templates", headers=auth_headers, json={"name": "pytest-agent-tpl-" + uuid.uuid4().hex[:6], "content": TPL_CONTENT, "variables": TPL_VARS})
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"/api/v1/prompt-templates/{r.json()['id']}", headers=auth_headers)


@pytest.fixture
def agents_cleanup(client, auth_headers):
    created: list[int] = []
    yield created
    for aid in created:
        client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)


def _payload(model_id: int, name: str, **extra) -> dict:
    return {"name": name, "description": "", "model_id": model_id, "params": {}, "kb_ids": [], "tool_ids": [], "workflow_id": None, **extra}


def _bind(client, auth_headers, agents_cleanup, model_id, template_id, name=None, variables=None) -> dict:
    name = name or "pytest-tpl-agent-" + uuid.uuid4().hex[:6]
    r = client.post("/api/v1/agents", headers=auth_headers, json=_payload(model_id, name, prompt_template_id=template_id, prompt_variables=variables or {"role": "客服"}))
    assert r.status_code == 200, r.text
    agents_cleanup.append(r.json()["id"])
    return r.json()


def test_binding_template_with_system_prompt_returns_400(client, auth_headers, model_id, template):
    r = client.post("/api/v1/agents", headers=auth_headers, json=_payload(model_id, "pytest-tpl-agent-both", system_prompt="手填", prompt_template_id=template["id"], prompt_variables={"role": "客服"}))
    assert r.status_code == 400 and r.json()["detail"] == "绑定模板时不能同时手填 system_prompt"


def test_missing_required_variable_returns_400_and_nothing_saved(client, auth_headers, model_id, template):
    name = "pytest-tpl-agent-missing-" + uuid.uuid4().hex[:6]
    r = client.post("/api/v1/agents", headers=auth_headers, json=_payload(model_id, name, prompt_template_id=template["id"], prompt_variables={"tone": "严肃"}))
    assert r.status_code == 400 and r.json()["detail"] == "缺少必填变量：role"
    assert client.get("/api/v1/agents", headers=auth_headers, params={"q": name}).json()["total"] == 0


def test_bound_agent_system_prompt_equals_rendered_template(client, auth_headers, model_id, template, agents_cleanup):
    a = _bind(client, auth_headers, agents_cleanup, model_id, template["id"])
    assert a["system_prompt"] == "你是客服，语气友好。"
    assert a["prompt_template_id"] == template["id"] and a["prompt_template_version"] == 1
    assert a["prompt_variables"] == {"role": "客服"} and a["prompt_template_outdated"] is False
    # 不绑定模板的智能体：三个字段为空，行为与以前相同
    plain = client.post("/api/v1/agents", headers=auth_headers, json=_payload(model_id, "pytest-tpl-agent-plain", system_prompt="手填提示词"))
    assert plain.status_code == 200, plain.text
    agents_cleanup.append(plain.json()["id"])
    assert plain.json()["prompt_template_id"] is None and plain.json()["prompt_variables"] == {} and plain.json()["system_prompt"] == "手填提示词"


def test_template_upgrade_marks_outdated_until_agent_is_resaved(client, auth_headers, model_id, template, agents_cleanup):
    a = _bind(client, auth_headers, agents_cleanup, model_id, template["id"])
    upd = client.put(f"/api/v1/prompt-templates/{template['id']}", headers=auth_headers, json={"name": template["name"], "content": "新版：你是{{role}}，语气{{tone}}。", "variables": TPL_VARS})
    assert upd.status_code == 200 and upd.json()["version"] == 2
    detail = client.get(f"/api/v1/agents/{a['id']}", headers=auth_headers).json()
    assert detail["prompt_template_outdated"] is True and detail["system_prompt"] == "你是客服，语气友好。"  # 不自动传播
    listed = client.get("/api/v1/agents", headers=auth_headers, params={"q": a["name"]}).json()["items"][0]
    assert listed["prompt_template_outdated"] is True
    # 重新保存即按模板当前版本重新渲染
    saved = client.put(f"/api/v1/agents/{a['id']}", headers=auth_headers, json=_payload(model_id, a["name"], prompt_template_id=template["id"], prompt_variables={"role": "客服", "tone": "严肃"}))
    assert saved.status_code == 200, saved.text
    assert saved.json()["prompt_template_outdated"] is False and saved.json()["prompt_template_version"] == 2
    assert saved.json()["system_prompt"] == "新版：你是客服，语气严肃。"


def test_publish_snapshot_includes_template_fields_and_rollback_restores_them(client, auth_headers, model_id, template, agents_cleanup):
    a = _bind(client, auth_headers, agents_cleanup, model_id, template["id"])
    aid = a["id"]
    assert client.post(f"/api/v1/agents/{aid}/publish", headers=auth_headers).status_code == 200
    bound_version = client.get(f"/api/v1/agents/{aid}/versions", headers=auth_headers).json()["items"][0]
    assert bound_version["snapshot"]["prompt_template_id"] == template["id"]
    assert bound_version["snapshot"]["prompt_template_version"] == 1 and bound_version["snapshot"]["prompt_variables"] == {"role": "客服"}
    # 解绑后再发布一版，快照里模板字段为空
    unbound = client.put(f"/api/v1/agents/{aid}", headers=auth_headers, json=_payload(model_id, a["name"], system_prompt="改成手填"))
    assert unbound.status_code == 200 and unbound.json()["prompt_template_id"] is None
    client.post(f"/api/v1/agents/{aid}/publish", headers=auth_headers)
    unbound_version = client.get(f"/api/v1/agents/{aid}/versions", headers=auth_headers).json()["items"][0]
    assert unbound_version["snapshot"]["prompt_template_id"] is None
    # 回滚到绑定版本：三个字段与渲染结果一起恢复
    rb = client.post(f"/api/v1/agents/{aid}/rollback/{bound_version['id']}", headers=auth_headers)
    assert rb.status_code == 200, rb.text
    assert rb.json()["prompt_template_id"] == template["id"] and rb.json()["prompt_template_version"] == 1
    assert rb.json()["prompt_variables"] == {"role": "客服"} and rb.json()["system_prompt"] == "你是客服，语气友好。"
    # 回滚到未绑定版本：三个字段恢复为空
    rb2 = client.post(f"/api/v1/agents/{aid}/rollback/{unbound_version['id']}", headers=auth_headers)
    assert rb2.json()["prompt_template_id"] is None and rb2.json()["prompt_variables"] == {} and rb2.json()["system_prompt"] == "改成手填"


def test_delete_bound_template_returns_409_until_unbound(client, auth_headers, model_id, template, agents_cleanup):
    a = _bind(client, auth_headers, agents_cleanup, model_id, template["id"])
    r = client.delete(f"/api/v1/prompt-templates/{template['id']}", headers=auth_headers)
    assert r.status_code == 409 and r.json()["detail"] == "仍有 1 个智能体绑定该模板"
    client.put(f"/api/v1/agents/{a['id']}", headers=auth_headers, json=_payload(model_id, a["name"], system_prompt="解绑"))
    assert client.delete(f"/api/v1/prompt-templates/{template['id']}", headers=auth_headers).status_code == 200


def _count_selects(fn) -> int:
    statements: list[str] = []

    def _listen(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _listen)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _listen)
    return len(statements)


def test_list_outdated_query_count_does_not_grow_with_agents(client, auth_headers, model_id, template, agents_cleanup):
    """列表算 outdated 只能一次 IN 批量查模板版本：1 个与 3 个绑定智能体的 SELECT 次数必须相同。"""
    one = "pytest-tpl-one-" + uuid.uuid4().hex[:6]
    _bind(client, auth_headers, agents_cleanup, model_id, template["id"], name=one + "-a")
    three = "pytest-tpl-three-" + uuid.uuid4().hex[:6]
    for suffix in ("a", "b", "c"):
        _bind(client, auth_headers, agents_cleanup, model_id, template["id"], name=f"{three}-{suffix}")
    count_one = _count_selects(lambda: client.get("/api/v1/agents", headers=auth_headers, params={"q": one}))
    count_three = _count_selects(lambda: client.get("/api/v1/agents", headers=auth_headers, params={"q": three}))
    assert count_one == count_three
