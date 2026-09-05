# 后端铁律卡片

完整规范见 `../docs/05-开发规范.md` 与 `../docs/06-后端规范.md`，本卡片只列改代码前必须记住的几条。

1. 改文件先读完整，再精确替换；禁止只读一段就整体写回。
2. 改完必验：`.venv/bin/python -c "from app.main import app"` 与 `PYTHONPATH=. .venv/bin/python -m pytest tests/ -v`。
3. 错误不吞：优先捕获具体异常类型；预期内的降级打 `logger.warning` 说明降到了什么，意外故障 `logger.exception` 留堆栈。禁止捕获后不留痕。
4. 新增降级路径三件事：打 WARN、接进 `system_service.get_system_status`、把降级信息写进数据本身（见 `docs/06` 第 13 节）。
5. 运行记录只走 `run_service.create_run / finalize_run`。
6. 路由不写业务，业务在 `services/`，服务层抛 `BizError(status, detail)`。
7. 表结构变更必落 `scripts/migrations/` 幂等脚本并更新 `docs/03`。
8. 接口变更同批改 `docs/04` 与 `frontend/src/api/<域>.ts`。
9. 密钥不进仓库、不进日志；共享库上的破坏性操作先确认。
10. 测试脚本写成 `.py` 文件，不用 shell 内联 JSON。
11. 列表接口的排序走 `core/pagination.apply_sort` 白名单（带 `id` 副键）、时间区间走 `time_range`（必须带时区、左闭右开）、批量写口走 `core/batch.run_batch`（逐条执行、逐条返回）；关联名称一页一次 `IN` 装配，禁止逐行查。
