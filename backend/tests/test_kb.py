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
