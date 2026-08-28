def test_list_tools(client, auth_headers):
    res = client.get("/api/v1/tools", headers=auth_headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_tool_crud(client, auth_headers):
    t = client.post("/api/v1/tools", headers=auth_headers, json={
        "name": "pytest-tool", "description": "测试工具", "type": "builtin", "config": {}, "timeout": 30,
    })
    assert t.status_code == 200, t.text
    tid = t.json()["id"]

    # 测试接口（内置工具 name 未知也会返回结果）
    r = client.post(f"/api/v1/tools/{tid}/test", headers=auth_headers, json={"args": {}})
    assert r.status_code == 200

    d = client.delete(f"/api/v1/tools/{tid}", headers=auth_headers)
    assert d.status_code == 200
