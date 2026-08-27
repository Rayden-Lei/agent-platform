# 智枢 · 智能体平台

统一管理大模型智能体的中台，覆盖智能体的配置、运行、编排、监控全生命周期。

## 技术栈
- 后端：FastAPI + SQLAlchemy 2.0 + LangChain + LangGraph + PostgreSQL(pgvector) + Redis + MinIO
- 前端：React 18 + TypeScript + Vite + Ant Design 5 + React Flow
- 部署：Docker Compose（私有化）

## 目录结构

```
agent-platform/
├── backend/            # 后端服务
│   ├── app/            # 应用代码（api/core/db/model_gateway/rag/workflow/tools）
│   ├── scripts/        # 数据库初始化脚本
│   ├── requirements.txt
│   └── .env            # 环境配置
├── frontend/           # 前端控制台
│   └── src/            # 页面/组件/接口/状态
├── docs/               # 设计文档
│   ├── 01-需求分析说明书.txt
│   ├── 02-架构设计说明书.txt
│   ├── 03-开发规范与铁律.md
│   └── agent-platform-design.docx  # 完整设计文档（SRS/ADD/DBD/API）
└── gen_docx.py         # 设计文档生成脚本
```

## 快速启动

### 后端（8000 端口）
```
cd backend
pip install -r requirements.txt
cp .env.example .env   # 按需修改数据库/模型配置
PYTHONPATH=. python3 scripts/setup_db.py
PYTHONPATH=. python3 scripts/init_db.py
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 前端（默认 5173，可指定端口）
```
cd frontend
npm install
npm run dev -- --port 18056 --host 0.0.0.0
```

## 默认账号
- 管理员：admin / admin123

## 核心能力
- 认证权限（JWT + 三级角色）
- 模型管理（多厂商接入，密钥加密）
- 智能体管理（创建/发布/版本）
- 对话（SSE 流式 + 多轮 + 工具调用 + RAG 引用）
- 知识库（文档解析/切片/向量化/检索）
- 工作流（可视化拖拽编排 + LangGraph 执行 + 节点日志）
- 运行监控（token 用量统计）

## 开发规范
见 docs/03-开发规范与铁律.md，所有开发必须遵守。

## Docker Compose 一键部署（私有化）

前置：安装 Docker 和 docker-compose 1.29+。

```
cd agent-platform
docker-compose up -d --build
```

启动 5 个容器：api(8000)、web(18056)、postgres(5432)、redis(6379)、minio(9000)。

- 前端控制台：http://<服务器IP>:18056
- 后端 API：http://<服务器IP>:8000
- 登录：admin / admin123
- 数据持久化：pgdata / miniodata 两个数据卷

配置项在根目录 .env（数据库密码、密钥等），首次部署按需修改。

停止：docker-compose down
停止并清空数据：docker-compose down -v
