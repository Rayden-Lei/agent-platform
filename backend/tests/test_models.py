def test_list_models(client, auth_headers):
    res = client.get("/api/v1/models", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["items"], list)
    assert body["page"] == 1 and body["total"] >= len(body["items"])


def test_model_crud(client, auth_headers):
    payload = {
        "name": "pytest-model",
        "provider": "openai",
        "api_base": "https://example.com/v1",
        "api_key": "sk-test",
        "model_name": "test-model",
        "default_params": {},
        "price_input": 1.0,
        "price_output": 2.0,
    }
    res = client.post("/api/v1/models", headers=auth_headers, json=payload)
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    assert res.json()["price_input"] == 1.0

    res = client.delete(f"/api/v1/models/{mid}", headers=auth_headers)
    assert res.status_code == 200
