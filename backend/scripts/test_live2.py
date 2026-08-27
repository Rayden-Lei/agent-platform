import httpx

base = "http://127.0.0.1:8000"
r = httpx.post(base + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
token = r.json()["token"]
h = {"Authorization": "Bearer " + token}

# 更新智能体：关联工具(calculator/current_time) + 知识库1
payload = {
    "name": "客服助手",
    "description": "内部客服",
    "system_prompt": "你是客服助手，会使用工具回答问题。",
    "model_id": 1,
    "params": {},
    "kb_ids": [1],
    "tool_ids": [1, 2],
    "workflow_id": None,
}
r = httpx.put(base + "/api/v1/agents/1", json=payload, headers=h)
print("更新智能体:", r.status_code, "status:", r.json()["status"], "tool_ids:", r.json()["tool_ids"], "kb_ids:", r.json()["kb_ids"])
r = httpx.post(base + "/api/v1/agents/1/publish", headers=h)
print("发布:", r.json()["status"], "version:", r.json()["version"])

def chat(msg):
    print(f"\n=== 问：{msg} ===")
    with httpx.stream("POST", base + "/api/v1/agents/1/chat", json={"message": msg}, headers=h, timeout=120) as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                print("  " + line[6:])

# 1. 工具调用测试
chat("请用计算器算一下 (2+3)*4 等于多少")

# 2. RAG 检索测试
chat("工作流是怎么编排的？")
