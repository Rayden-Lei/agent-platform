"""工作流 CRUD 与运行的冒烟用例。

发布语义（FR-075）：建出来的工作流是草稿，run 一律读线上发布版本，未发布 403。
所以这里先发布再运行；发布 / 回滚 / 版本历史的完整语义在 test_workflow_publish.py。
"""
from tests.conftest import publish_workflow


def test_workflow_crud_and_run(client, auth_headers):
    w = client.post("/api/v1/workflows", headers=auth_headers, json={
        "name": "pytest-workflow", "description": "",
        "graph": {
            "nodes": [
                {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
                {"id": "e", "type": "end", "config": {}},
            ],
            "edges": [{"from": "s", "to": "e"}],
        },
    })
    assert w.status_code == 200, w.text
    wid = w.json()["id"]
    assert w.json()["status"] == "draft" and w.json()["published_version"] is None

    publish_workflow(client, auth_headers, wid)
    r = client.post(f"/api/v1/workflows/{wid}/run", headers=auth_headers, json={"inputs": {"input": "hello"}})
    assert r.status_code == 200

    d = client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)
    assert d.status_code == 200
