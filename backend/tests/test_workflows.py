def test_workflow_crud_and_run(client, auth_headers):
    w = client.post("/api/v1/workflows", headers=auth_headers, json={
        "name": "pytest-workflow", "description": "",
        "graph": {
            "nodes": [
                {"id": "s", "type": "start", "config": {}},
                {"id": "e", "type": "end", "config": {}},
            ],
            "edges": [{"from": "s", "to": "e"}],
        },
    })
    assert w.status_code == 200, w.text
    wid = w.json()["id"]

    r = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"input": "hello"})
    assert r.status_code == 200

    d = client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)
    assert d.status_code == 200
