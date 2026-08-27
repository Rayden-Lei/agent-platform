import time

import httpx

base = "http://127.0.0.1:8000"
r = httpx.post(base + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
token = r.json()["token"]
h = {"Authorization": "Bearer " + token}

# 1. 创建知识库
r = httpx.post(base + "/api/v1/knowledge-bases", json={"name": "产品说明库", "chunk_size": 100, "chunk_overlap": 20}, headers=h)
print("创建知识库:", r.status_code, r.json())
kb_id = r.json()["id"]

# 2. 上传文档
doc_text = "智能体中台是一个统一管理大模型智能体的平台。\n它支持模型管理、智能体创建、工作流编排和知识库检索。\n知识库检索采用向量化技术，实现语义搜索。\n用户可以通过拖拽方式编排工作流，无需编写代码。\n平台支持国产和国外大模型，私有化部署保障数据安全。"
files = {"file": ("说明.txt", doc_text.encode("utf-8"), "text/plain")}
r = httpx.post(base + f"/api/v1/knowledge-bases/{kb_id}/documents", files=files, headers=h)
print("上传文档:", r.status_code, r.json())
doc_id = r.json()["id"]

# 3. 轮询文档状态
for _ in range(20):
    r = httpx.get(base + f"/api/v1/knowledge-bases/{kb_id}/documents", headers=h)
    docs = r.json()
    status = docs[0]["status"]
    print("文档状态:", status, "chunk_count:", docs[0]["chunk_count"])
    if status in ("ready", "failed"):
        break
    time.sleep(1)

# 4. 检索
r = httpx.post(base + f"/api/v1/knowledge-bases/{kb_id}/search", json={"query": "工作流怎么编排", "top_k": 3}, headers=h)
print("检索结果:", r.status_code)
for item in r.json().get("items", []):
    print("  score:", item["score"], "| content:", item["content"][:50])
