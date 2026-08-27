import time

import httpx

base = "http://127.0.0.1:8000"
tok = httpx.post(base + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]
h = {"Authorization": "Bearer " + tok}

# 上传文档
doc_text = "智枢平台支持可视化编排工作流。\n工作流由节点和连线组成，可以拖拽搭建。\n平台还支持知识库检索，用向量化技术实现语义搜索。\n智能体可以调用工具和知识库完成任务。"
files = {"file": ("产品说明.txt", doc_text.encode("utf-8"), "text/plain")}
r = httpx.post(base + "/api/v1/knowledge-bases/1/documents", files=files, headers=h)
print("上传:", r.status_code, r.json())
doc_id = r.json()["id"]

# 轮询状态
for _ in range(30):
    r = httpx.get(base + "/api/v1/knowledge-bases/1/documents", headers=h)
    d = r.json()[0]
    if d["status"] in ("ready", "failed"):
        print("文档状态:", d["status"], "chunk:", d["chunk_count"], "error:", d.get("error"))
        break
    time.sleep(1)

# 检索（真实语义向量）
r = httpx.post(base + "/api/v1/knowledge-bases/1/search", json={"query": "怎么搭建工作流", "top_k": 3}, headers=h)
print("检索结果:")
for it in r.json().get("items", []):
    print("  score:", it["score"], "|", it["content"][:50])
