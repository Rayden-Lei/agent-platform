"""Prompt 模板（`12-差距补齐开发计划.md` 2.7，FR-028）：渲染纯函数 + 接口（校验、版本、回滚、渲染、权限）。"""
import uuid

import pytest

from app.core.prompt_render import extract_variables, render

VARS = [
    {"name": "role", "description": "角色", "required": True, "default": None},
    {"name": "tone", "description": "语气", "required": False, "default": "友好"},
    {"name": "spare", "description": "没用到", "required": False, "default": None},
]
CONTENT = "你是{{role}}，请用{{ tone }}的语气回答。"


# ---------- 渲染纯函数 ----------

def test_extract_variables_handles_spaces_and_duplicates():
    assert extract_variables("{{a}} {{ b }} {{a}} {{1bad}} {{c-d}}") == {"a", "b"}


def test_render_reports_missing_required():
    result = render(CONTENT, VARS, {})
    assert result.missing == ["role"]
    assert "{{role}}" in result.text and "友好" in result.text  # 缺失的占位符原样保留，其余照常替换


def test_render_uses_default_when_value_absent_and_value_overrides_default():
    assert render(CONTENT, VARS, {"role": "客服"}).text == "你是客服，请用友好的语气回答。"
    assert render(CONTENT, VARS, {"role": "客服", "tone": "严肃"}).text == "你是客服，请用严肃的语气回答。"
    assert render(CONTENT, VARS, {"role": "客服", "tone": ""}).text == "你是客服，请用友好的语气回答。"  # 空串视为未传


def test_render_lists_unused_declared_variables_and_ignores_undeclared_values():
    result = render(CONTENT, VARS, {"role": "客服", "extra": "x"})
    assert result.unused == ["spare"] and result.missing == []


# ---------- 接口 ----------

def _payload(name: str, content: str = CONTENT, variables: list | None = None, description: str = "") -> dict:
    return {"name": name, "description": description, "content": content, "variables": VARS if variables is None else variables}


@pytest.fixture
def template(client, auth_headers):
    """一个新建的模板，用例结束后删除。"""
    r = client.post("/api/v1/prompt-templates", headers=auth_headers, json=_payload("pytest-tpl-" + uuid.uuid4().hex[:8]))
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"/api/v1/prompt-templates/{r.json()['id']}", headers=auth_headers)


def test_create_returns_content_version_and_unused_variables(client, auth_headers, template):
    assert template["version"] == 1 and template["content"] == CONTENT
    assert template["unused_variables"] == ["spare"]
    assert [v["name"] for v in template["variables"]] == ["role", "tone", "spare"]
    versions = client.get(f"/api/v1/prompt-templates/{template['id']}/versions", headers=auth_headers).json()
    assert [v["version"] for v in versions["items"]] == [1]  # 初版也有快照，才能回滚回来
    listed = client.get("/api/v1/prompt-templates", headers=auth_headers, params={"q": template["name"]}).json()
    assert listed["items"][0]["id"] == template["id"] and "content" not in listed["items"][0]


def test_content_referencing_undeclared_variable_returns_400(client, auth_headers):
    r = client.post("/api/v1/prompt-templates", headers=auth_headers, json=_payload("pytest-tpl-undeclared", content="你是{{role}}，语气{{tone}}，{{style}}", variables=VARS[:1]))
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "模板引用了未声明的变量：style, tone"


def test_duplicate_name_returns_409(client, auth_headers, template):
    r = client.post("/api/v1/prompt-templates", headers=auth_headers, json=_payload(template["name"]))
    assert r.status_code == 409 and r.json()["detail"] == "模板名称已存在"


def test_changing_content_bumps_version_and_writes_snapshot(client, auth_headers, template):
    r = client.put(f"/api/v1/prompt-templates/{template['id']}", headers=auth_headers, json=_payload(template["name"], content=CONTENT + "简短一点。"))
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2
    versions = client.get(f"/api/v1/prompt-templates/{template['id']}/versions", headers=auth_headers).json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["content"].endswith("简短一点。") and versions[1]["content"] == CONTENT


def test_renaming_only_keeps_version(client, auth_headers, template):
    r = client.put(f"/api/v1/prompt-templates/{template['id']}", headers=auth_headers, json=_payload(template["name"] + "-renamed", description="改了描述"))
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1 and r.json()["name"].endswith("-renamed")


def test_rollback_bumps_version_and_restores_content(client, auth_headers, template):
    client.put(f"/api/v1/prompt-templates/{template['id']}", headers=auth_headers, json=_payload(template["name"], content="第二版 {{role}}", variables=VARS[:1]))
    v1 = next(v for v in client.get(f"/api/v1/prompt-templates/{template['id']}/versions", headers=auth_headers).json()["items"] if v["version"] == 1)
    r = client.post(f"/api/v1/prompt-templates/{template['id']}/rollback/{v1['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 3 and r.json()["content"] == CONTENT and len(r.json()["variables"]) == 3
    versions = client.get(f"/api/v1/prompt-templates/{template['id']}/versions", headers=auth_headers).json()["items"]
    assert [v["version"] for v in versions] == [3, 2, 1]


def test_rollback_to_other_templates_version_returns_404(client, auth_headers, template):
    other = client.post("/api/v1/prompt-templates", headers=auth_headers, json=_payload("pytest-tpl-other-" + uuid.uuid4().hex[:6])).json()
    try:
        other_v1 = client.get(f"/api/v1/prompt-templates/{other['id']}/versions", headers=auth_headers).json()["items"][0]["id"]
        r = client.post(f"/api/v1/prompt-templates/{template['id']}/rollback/{other_v1}", headers=auth_headers)
        assert r.status_code == 404 and r.json()["detail"] == "版本不存在"
    finally:
        client.delete(f"/api/v1/prompt-templates/{other['id']}", headers=auth_headers)


def test_render_missing_required_returns_400_and_success_returns_text(client, auth_headers, template):
    r = client.post(f"/api/v1/prompt-templates/{template['id']}/render", headers=auth_headers, json={"variables": {"tone": "严肃"}})
    assert r.status_code == 400 and r.json()["detail"] == "缺少必填变量：role"
    ok = client.post(f"/api/v1/prompt-templates/{template['id']}/render", headers=auth_headers, json={"variables": {"role": "客服"}})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"content": "你是客服，请用友好的语气回答。", "missing": [], "unused": ["spare"]}


def test_more_than_30_variables_returns_422(client, auth_headers):
    variables = [{"name": f"v{i}", "required": False} for i in range(31)]
    r = client.post("/api/v1/prompt-templates", headers=auth_headers, json=_payload("pytest-tpl-31", content="x", variables=variables))
    assert r.status_code == 422


def test_duplicate_variable_name_returns_422(client, auth_headers):
    variables = [{"name": "a"}, {"name": "a"}]
    r = client.post("/api/v1/prompt-templates", headers=auth_headers, json=_payload("pytest-tpl-dup", content="{{a}}", variables=variables))
    assert r.status_code == 422 and "变量名重复：a" in r.json()["detail"][0]["msg"]


def test_caller_role_is_forbidden(client, auth_headers, template):
    username = "pytest-caller-" + uuid.uuid4().hex[:6]
    created = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "caller123", "role": "caller"})
    assert created.status_code == 200, created.text
    try:
        token = client.post("/api/v1/auth/login", json={"username": username, "password": "caller123"}).json()["token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/api/v1/prompt-templates", headers=headers).status_code == 403
        assert client.get(f"/api/v1/prompt-templates/{template['id']}", headers=headers).status_code == 403
        assert client.post(f"/api/v1/prompt-templates/{template['id']}/render", headers=headers, json={"variables": {}}).status_code == 403
    finally:
        client.delete(f"/api/v1/users/{created.json()['id']}", headers=auth_headers)


def test_api_key_is_forbidden(client, auth_headers, template):
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-tpl-key", "quota": 10}).json()
    try:
        r = client.get("/api/v1/prompt-templates", headers={"Authorization": "Bearer " + key["key"]})
        assert r.status_code == 403 and "API Key" in r.json()["detail"]
    finally:
        client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_headers)


def test_delete_cascades_versions_and_get_returns_404(client, auth_headers):
    t = client.post("/api/v1/prompt-templates", headers=auth_headers, json=_payload("pytest-tpl-del-" + uuid.uuid4().hex[:6])).json()
    assert client.delete(f"/api/v1/prompt-templates/{t['id']}", headers=auth_headers).status_code == 200
    assert client.get(f"/api/v1/prompt-templates/{t['id']}", headers=auth_headers).status_code == 404
    assert client.get(f"/api/v1/prompt-templates/{t['id']}/versions", headers=auth_headers).status_code == 404
