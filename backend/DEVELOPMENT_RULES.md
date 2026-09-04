# 后端铁律卡片

完整规范见 `../docs/05-开发规范.md` 与 `../docs/06-后端规范.md`，本卡片只列改代码前必须记住的几条。

1. 改文件先读完整，再精确替换；禁止只读一段就整体写回。
2. 改完必验：`.venv/bin/python -c "from app.main import app"` 与 `PYTHONPATH=. .venv/bin/python -m pytest tests/ -v`。
3. 错误不吞：禁止 `except Exception: pass`；要么处理，要么 `logger.exception`。
4. 运行记录只走 `run_service.create_run / finalize_run`。
5. 路由不写业务，业务在 `services/`，服务层抛 `BizError(status, detail)`。
6. 表结构变更必落 `scripts/migrations/` 幂等脚本并更新 `docs/03`。
7. 接口变更同批改 `docs/04` 与 `frontend/src/api/index.ts`。
8. 密钥不进仓库、不进日志；共享库上的破坏性操作先确认。
9. 测试脚本写成 `.py` 文件，不用 shell 内联 JSON。
