# 后端服务

FastAPI + SQLAlchemy 2.0 + LangChain / LangGraph + PostgreSQL（pgvector）+ Redis + MinIO + APScheduler。

## 目录

```
app/
  main.py            应用装配：日志、CORS、路由、启动建表与初始化管理员、调度器
  config.py          pydantic-settings 读 .env
  api/v1/            一模块一路由文件，router.py 汇总
  schemas/           多路由共享的 Pydantic 模型
  services/          业务规则与事务边界
  core/              security / deps / exceptions / audit / scheduler
  db/                base / session / models（17 张表）
  model_gateway/     数据库模型配置 → LangChain ChatModel
  rag/               parser / pipeline / embeddings / retriever / rerank / minio_client
  workflow/engine.py 工作流 JSON → LangGraph 图，10 类节点
  tools/             executor（内置 + HTTP）、langchain_tools
scripts/
  setup_db.py        建库 + vector 扩展
  init_db.py         建表 + 管理员（应用启动也会做）
  migrations/        幂等迁移脚本，按文件名顺序执行
  test_*.py          手工联调脚本
tests/               pytest
```

## 启动

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt pytest
cp .env.example .env
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 验证

```bash
.venv/bin/python -c "from app.main import app"
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
```

细节见 `../docs/06-后端规范.md` 与 `../docs/08-运行与部署.md`。
