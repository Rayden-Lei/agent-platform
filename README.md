# 智枢 · 智能体平台

统一管理大模型智能体的中台：模型接入、智能体配置与发布、流式对话、知识库检索增强、可视化工作流编排与执行、运行监控、审计、API Key 与定时调度。私有化部署。

## 技术栈

- 后端：FastAPI + SQLAlchemy 2.0 + LangChain / LangGraph + PostgreSQL（pgvector）+ Redis + MinIO + APScheduler
- 前端：React 18 + TypeScript + Vite + Ant Design 5 + React Flow + zustand + axios
- 部署：Docker Compose 一键私有化，或裸机 uvicorn + 外部数据服务

## 目录

```
agent-platform/
├── backend/                 # 后端服务（FastAPI）
│   ├── app/                 # api / services / core / db / model_gateway / rag / workflow / tools
│   ├── scripts/             # 建库脚本、幂等迁移脚本、联调脚本
│   ├── tests/               # pytest
│   ├── requirements.txt
│   └── .env.example         # 后端环境变量模板
├── frontend/                # 前端控制台（React）
│   └── src/                 # api / components / pages / store
├── docs/                    # 全部文档，从 docs/README.md 进入
├── docker-compose.yml
├── .env.example             # Docker Compose 环境变量模板
└── gen_docx.py              # 把 docs/01～04 渲染成 Word 设计文档
```

## 快速启动

要求 Python 3.12+（uv 管理）、Node 20+、可用的 PostgreSQL（pgvector）/ Redis / MinIO。完整步骤与环境变量说明见 `docs/08-运行与部署.md`。

后端：

```bash
cd backend
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env                      # 修改数据库、Redis、MinIO、密钥
PGPASSWORD=<密码> .venv/bin/python scripts/setup_db.py
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```bash
cd frontend
npm install
npm run dev -- --port 18056 --host 0.0.0.0
```

默认管理员 `admin / admin123`，首次登录后请修改。

## Docker Compose 部署

```bash
cp .env.example .env        # 改密码与密钥
docker compose up -d --build
```

启动 api（8000）、web（18056）、postgres、redis、minio 五个容器；控制台 `http://<主机>:18056`。详见 `docs/08-运行与部署.md`。

## 文档

| 文档 | 内容 |
|---|---|
| `docs/01-需求说明.md` | 功能需求、角色权限、实现状态、验收标准 |
| `docs/02-架构设计.md` | 分层、代码结构、对话 / RAG / 工作流核心链路、设计决策 |
| `docs/03-数据库设计.md` | 17 张表、外键语义、JSON 字段结构、迁移管理 |
| `docs/04-接口设计.md` | 全部接口、响应结构、错误码、SSE 事件契约、分页与 API Key 契约 |
| `docs/05-开发规范.md` | 铁律、流程、命名、错误处理、测试、提交 |
| `docs/06-后端规范.md` | 分层、路由与服务写法、节点 / 工具 / RAG 扩展、迁移脚本 |
| `docs/07-前端规范.md` | 页面骨架与滚动、请求层、三态、视觉与品牌、表格表单 |
| `docs/08-运行与部署.md` | 本地开发、环境变量、迁移、两种部署、排障 |
| `docs/09-演进路线.md` | 改进优先级与已知问题 |
| `docs/10-差距分析.md` | 面向企业级 AI 能力中台的 6 层差距盘点（一次性现状分析） |

所有开发必须遵守 `docs/05`～`07`。
