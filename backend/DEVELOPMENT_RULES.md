# 后端开发规范与铁律（简版）

完整版见 docs/03-开发规范与铁律.txt

## 铁律
1. 改文件先 read 完整，再 edit；严禁 read 部分 + write 回写（会截断文件）。
2. 改完必验：PYTHONPATH=. python3 -c "from app.main import app"
3. 测试用 .py 脚本文件，禁止 shell -c 内联复杂 JSON。

## 分层
api 路由 / services 业务 / core 安全鉴权异常 / db 模型会话 /
model_gateway 模型 / rag 知识库 / workflow 工作流 / tools 工具 / tasks 任务

## 框架
FastAPI + SQLAlchemy 2.0 + Alembic；LangChain ChatOpenAI（OpenAI 兼容）；
agent 用 create_agent；工作流用 LangGraph StateGraph；向量用 pgvector。

## 安全
bcrypt 密码、AES 密钥加密、JWT + 三角色鉴权、接口返回密钥脱敏、日志不落敏感信息。

## 接口
REST + JSON，前缀 /api/v1，统一 code/message/data，分页 page/page_size，
流式 SSE，错误码 401/403/404/422/500/504。