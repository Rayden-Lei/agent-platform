import httpx

base = "http://127.0.0.1:8000"
tok = httpx.post(base + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]
h = {"Authorization": "Bearer " + tok}

# 正确的 input JSON 字符串
payload = {"input": '{"expression": "100/4"}'}
r = httpx.post(base + "/api/v1/workflows/1/run", json=payload, headers=h, timeout=60)
print("run:", r.json())
rid = r.json().get("run_id")
if rid:
    d = httpx.get(base + "/api/v1/runs/" + str(rid), headers=h).json()
    print("节点日志:", d.get("nodes"))
