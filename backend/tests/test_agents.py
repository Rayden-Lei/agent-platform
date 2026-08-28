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
    assert len(v.json()) >= 1

    rb = client.post(f"/api/v1/agents/{aid}/rollback/{v.json()[0]['id']}", headers=auth_headers)
    assert rb.status_code == 200

    d = client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)
    assert d.status_code == 200
    client.delete(f"/api/v1/models/{model_id}", headers=auth_headers)
