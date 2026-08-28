import time
import httpx

base = "http://127.0.0.1:8000"
tok = httpx.post(base + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]
h = {"Authorization": "Bearer " + tok}

# 上传 CSV（表格按行分片）
csv_content = "商品,价格,库存\n苹果,5元,100\n香蕉,3元,200\n橙子,6元,150"
files = {"file": ("价格表.csv", csv_content.encode("utf-8"), "text/csv")}
r = httpx.post(base + "/api/v1/knowledge-bases/1/documents", files=files, headers=h)
print("上传 CSV:", r.status_code, r.json())
doc_id = r.json()["id"]

for _ in range(30):
    r = httpx.get(base + "/api/v1/knowledge-bases/1/documents", headers=h)
    d = [x for x in r.json() if x["id"] == doc_id][0]
    if d["status"] in ("ready", "failed"):
        print("CSV 文档状态:", d["status"], "| chunk 数:", d["chunk_count"], "| 错误:", d.get("error"))
        break
    time.sleep(1)

# 检索表格内容
r = httpx.post(base + "/api/v1/knowledge-bases/1/search", json={"query": "香蕉多少钱", "top_k": 3}, headers=h)
print("检索结果:")
for it in r.json().get("items", []):
    print("  score:", it["score"], "|", it["content"][:60])
