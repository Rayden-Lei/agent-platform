import httpx

base = "http://127.0.0.1:8000"
r = httpx.post(base + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
token = r.json()["token"]
h = {"Authorization": "Bearer " + token}

# 运行工作流，input 为合法的 JSON 字符串
payload = {"input": '{"expression": "2+3*4"}'}
r2 = httpx.post(base + "/api/v1/workflows/1/run", json=payload, headers=h, timeout=60)
print("run status:", r2.status_code)
print("run result:", r2.json())

r3 = httpx.get(base + "/api/v1/workflows/1/runs", headers=h)
print("runs:", r3.json())
