# 智能体中台 - 后端服务

技术栈：FastAPI + SQLAlchemy 2.0 + PostgreSQL(pgvector) + Redis + MinIO

## 目录结构
app/
  main.py            应用入口
  config.py          配置（.env）
  db/                base/session/models（14 张表）
  core/              security（JWT/bcrypt/AES）、deps（鉴权依赖）
  schemas/           Pydantic 模型
  api/v1/            auth/users/models/agents 路由
  model_gateway/     模型网关（待实现）
  rag/               RAG 管道（待实现）
  workflow/          工作流引擎（待实现）
  tools/             工具执行器（待实现）
  tasks/             后台任务（待实现）
scripts/
  setup_db.py        创建数据库 + vector 扩展
  init_db.py         建表 + 初始化管理员

## 快速开始
1. 安装依赖：pip install -r requirements.txt
2. 配置 .env（参考 .env.example）
3. 初始化数据库：
   PYTHONPATH=. python3 scripts/setup_db.py
   PYTHONPATH=. python3 scripts/init_db.py
4. 启动：python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
5. 健康检查：curl http://127.0.0.1:8000/health

## 默认账号
admin / admin123（角色 admin）

## 已完成
- JWT 登录/me、角色鉴权（admin/developer/caller）
- 用户管理（管理员 CRUD）
- 模型管理（CRUD + API 密钥 AES 加密）
- 智能体管理（CRUD + 发布版本）
- 14 张表数据库模型（含 pgvector 向量列）

## 待实现
- 模型网关（chat/chat_stream 流式）
- 对话运行时（SSE + 工具调用循环 + RAG 检索）
- 工具执行器（内置 + HTTP）
- RAG 管道（文档解析/切片/向量化/检索）
- 工作流引擎（DAG 拓扑执行 + 6 类节点）
- 知识库/文档/工作流/运行记录 API
