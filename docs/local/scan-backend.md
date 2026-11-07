# 后端 app/ 代码质量与健壮性扫描（只读）

审查日期：2026-11-08　范围：`backend/app`（108 个 py，约 16k 行）
审查依据：`backend/DEVELOPMENT_RULES.md`、`docs/05-开发规范.md`、`docs/06-后端规范.md`
口径：只报真实缺陷（什么场景下会出事），不报风格偏好；存量代码现状不构成规范。

**已覆盖**：services/* 全部 24 个、tools/*（executor / permission / schema / langchain_tools / general / builtin / tool_config）、
core/*（audit / batch / deps / middleware / pagination / rate_limiter / redis_client / scheduler / security / request_context / ip_filter / http / prompt_render / limits / exceptions）、
db/models.py 与 db/session.py、workflow/engine.py、rag/*（pipeline / retriever / embeddings / minio_client）、
runtime/*（sandbox / agent_config）、model_gateway/*、mcp/client.py、api/v1 全部 22 个路由文件（逐个核对了鉴权依赖）。

**未逐行读**：api/v1/router.py、services/chat_events.py、services/chat_trace.py、rag/parser.py、rag/rerank.py、model_gateway/reasoning.py、
api/v1/embedding_models.py、api/v1/models.py、api/v1/prompt_templates.py、api/v1/shares.py（仅按调用关系与 grep 覆盖）。

**分层现状（合规项，如实记录）**：api 层 0 处 `db.query/db.get/db.execute`、0 处原生 SQL、0 处 f-string 拼 SQL；
排序全部走 `core.pagination.apply_sort` 白名单；列表关联名称基本都是「一页一次 IN」；未发现裸 `except:`（0 处）。

---

## P0：会导致数据错 / 越权 / 静默失效

### 1. 白名单通配符：文档承诺支持，执行闸门实际不支持
- `app/tools/permission.py:78`：`if any(host == item or host.endswith("." + item) for item in allowed)`
- `app/tools/tool_config.py:70`：工具页说明写的是「逗号分隔，支持 `*.example.com` 后缀通配」
- **会出事的场景**：管理员照工具页的说明把 `allowed_hosts` 填成 `["*.example.com"]`。此时匹配条件是 `host.endswith(".*.example.com")`，任何真实域名都匹配不上 → 该工具 100% 被拒，模型侧只看到「目标地址不在白名单内」，而配置看起来完全正确。排查成本极高（配置「没错」）。
- 对照：内置工具的白名单 `app/tools/general.py:221` 是**真的支持**通配的（`p.startswith("*.") and h.endswith(p[1:])`）。同一概念两套语义。
- **建议**：`permission.check` 复用 `general._host_allowed` 的匹配逻辑（或抽出 `core` 里的共用函数），并补一条用例钉住 `*.example.com` 命中 `v2.example.com`。

### 2. `record_audit` 自带 commit，把调用方的半成品事务一起提交
- `app/core/audit.py:27`（`db.commit()`），docstring 自己已承认「若调用方在同一事务中还有未提交的修改，会一并提交，且此后无法再整体回滚」
- 典型调用点：`app/services/kb_service.py:147-150`（`db.flush()` → `record_audit` → `db.refresh` → `_serialize`）
- **会出事的场景**：`create_kb` 里 audit 已经把知识库行提交了；紧接着 `_serialize` 里 `_stats_by_kb` 抛异常（如连接闪断），接口返回 500，但库里的知识库已经存在。用户以为失败、重试一次，得到两个同名知识库。同类风险在 `skill_service.delete_skill`、`mcp_service.create_server`、`tool_service.create_tool` 等所有「先写库再 audit」的位置。
- **建议**：`record_audit` 改成只 `db.add`，由调用方在同一事务里 commit；或显式提供 `record_audit(..., commit=False)` 并让写操作统一用它。

### 3. 删除技能：先删库提交，再清对象存储，且审计没写
- `app/services/skill_service.py:167-173`：`db.delete(s)` → `db.commit()` → `skill_resource.drop_all(...)` → `record_audit(...)`
- **会出事的场景**：MinIO 抖动/网络错时 `drop_all` 抛异常 → 技能行**已经删掉**、审计**没写**、对象**留在桶里**，接口返回 500。使用者看到「删除失败」，刷新后技能没了；对象成为永久孤儿（没有任何回收路径）。
- **建议**：先摘对象（失败只记 WARN 并留下待清理标记），再删库；审计与删除放同一事务（配合第 2 条）。

### 4. 工具节点按 `Tool.name` 查且 name 无唯一约束
- `app/workflow/engine.py:289`：`db.query(Tool).filter(Tool.name == tool_name).first()`
- `app/db/models.py:175`：`name: Mapped[str] = mapped_column(String(128), nullable=False)` —— 没有 `unique`
- **会出事的场景**：两个工具同名（手工建的工具允许重名；MCP 同步名是 `{server}_{remote}` 拼接，不同服务器可能撞名）时，`.first()` 取哪一行取决于物理顺序。工作流会**静默调用另一个工具**——参数声明、白名单、鉴权全都不一样，运行记录上看不出异常。
- **建议**：给 `tools.name` 加唯一约束（迁移脚本），或把工作流节点改成按 `tool_id` 引用；至少 `.first()` 改成 `.one_or_none()` 并在多行时报 400。

---

## P1：会 500 / 会静默失败 / 会打爆资源

### 5. 删用户的引用检查漏了 Skill 与 PromptTemplate（撞 RESTRICT → 500）
- `app/services/user_service.py:96-106` 只检查了 模型 / 智能体 / 知识库 / 工作流 / 分享链接
- 但 `app/db/models.py:101`（PromptTemplate.created_by）与 `app/db/models.py:140`（Skill.created_by）都是 `ondelete="RESTRICT"`
- **会出事的场景**：删一个建过提示词模板或技能的用户 → 前 5 项全过 → `db.delete(u)` 撞外键 → `IntegrityError` 冒到全局处理器 → **500**「服务器内部错误」，而不是可读的 409「该用户仍关联…」。规范 06 第 3 节明说「被 RESTRICT 保护的删除，先查引用数给出可读的 409，不要让数据库报错冒到 500」。
- **建议**：`refs` 里补 Skill、PromptTemplate、EmbeddingModel（`models.py:218` 是 SET NULL，可不补）。

### 6. HTTP 工具返回值不做类型与体积约束，下游按 dict 用
- `app/tools/executor.py:192`：`return resp.json()` —— 远端返回什么就返回什么，无体积上限
- `app/workflow/engine.py:308`：`if result.get("denied")` 直接对返回值调 `.get`
- **会出事的场景**：(a) 远端返回 JSON 数组 `[...]` 或字符串 → `.get` 抛 `AttributeError: 'list' object has no attribute 'get'`，节点失败，错误信息与真实原因（工具返回类型不对）毫无关系；(b) 远端返回 50MB JSON → 原样进 `json.dumps` 塞进模型上下文，一次调用吃光窗口并可能 OOM。内置的 `http_request` 是有 `max_bytes` 截断的（`general.py:322`），HTTP 工具没有。
- **建议**：`_execute_http` 统一返回 `{"result": ...}`（非 dict 时包一层），并加响应体字节上限（复用 `TOOL_HTTP_MAX_BYTES`）。

### 7. 会话消息接口无上限、无分页
- `app/services/conversation_service.py:170`：`db.query(Message).filter(...).order_by(Message.id).all()`，每条含 `tool_calls`（落库 ≤8000 字/条）与 `citations` 全量 JSON
- **会出事的场景**：一个几百轮、每轮带工具结果的长会话，`GET /conversations/{id}/messages` 一次返回几十 MB；前端渲染卡死，DB 与出口带宽一起被打满。规范 06 第 4 节要求列表一律分页。
- **建议**：加 `PageParams`（默认倒序取最近 N 条，前端滚到顶再取），或至少给条数硬上限。

### 8. 每次对话完成都起一个 daemon 线程去调模型，线程数无界
- `app/services/chat_service.py:150`：`threading.Thread(target=_run, ...).start()`（`schedule_summary_refresh`）
- **会出事的场景**：高峰期每秒几十轮对话结束 → 同时几十个线程各持一个 `SessionLocal` + 一次完整 LLM 调用（可能 10 秒以上）。线程、DB 连接、上游并发三者同时膨胀，且没有任何上限或排队。
- **建议**：改成一个有界队列 + 固定 worker 池（如 `ThreadPoolExecutor(max_workers=2)`），队列满时丢弃并 WARN。

### 9. 检索的线程池嵌套，并发数被放大
- `app/services/chat_service.py:223`：外层 `ThreadPoolExecutor(max_workers=min(8, len(pairs)))`
- `app/rag/retriever.py:123`：内层又开 `ThreadPoolExecutor(max_workers=min(8, len(keywords)))`
- **会出事的场景**：绑 20 个知识库 × 3 个改写查询 = 60 个 pair → 外层 8 线程，每线程内层最多 8 → 理论 64 路并发 DB 连接 + 64 路 embed 请求。SQLAlchemy 默认池 5+10 溢出，直接耗尽并开始 `TimeoutError`。
- **建议**：内层关键词检索改成串行（关键词通常 3～5 个，收益远小于成本），或全局限流一个共享池。

### 10. 技能 / 工具的「绑定数」是整表扫描，与分页无关
- `app/services/skill_service.py:68`（`bound_agent_count`）与 `:89`（`list_skills`）：`db.query(Agent.id, Agent.skill_ids).filter(Agent.skill_ids != [])` 全表拉回内存
- `app/services/tool_service.py:141`：`for (ids,) in db.query(Agent.tool_ids).all()` 同理
- **会出事的场景**：智能体到几千行时，**每次打开技能列表 / 工具列表**（哪怕只看第一页 20 条）都把整张 agents 表（含 JSONB）读进 Python。这是规范 06 第 4 节「禁止 N+1」的另一面：把 N+1 换成了全表扫。
- **建议**：JSONB 加 GIN 索引后用 `contains` 在库侧聚合；或至少只在需要时算（列表页展示数可以懒加载/缓存）。

### 11. 知识库上传把整个文件读进内存，上限 200MB × 并发数
- `app/api/v1/kb.py:174`：`buf.extend(chunk)`，上限来自 `settings.KB_UPLOAD_MAX_MB`（默认 200，`config.py:48`）
- **会出事的场景**：5 个并发上传 200MB 文件 → 1GB 常驻内存，容器 OOM 被杀（进程一死，正在处理的文档全变孤儿）。
- **建议**：改成流式落盘/直传 MinIO（`put_object` 支持流），或把并发上传数也纳入限流。

### 12. 文档解析挂在 BackgroundTasks，占的是请求线程池
- `app/api/v1/kb.py:166,212,220,228`：`background_tasks.add_task(process_document, doc.id)`
- `app/rag/pipeline.py:151-158`：拿不到信号量时 `while not slot.acquire(timeout=interval)` **阻塞等待**
- **会出事的场景**：`process_document` 是同步函数，Starlette 把它丢进 anyio 的默认线程池（40 线程）。一篇几十 MB 的 xlsx 要跑几十分钟，期间那个线程一直被占；几个大文件并发上传就能把线程池占满，**所有同步路由（FastAPI 里大量 `def` 路由跑在同一个池）一起排队**，表现为整站变慢。
- **建议**：解析改走独立的 worker（自己的线程 + 队列），不要复用请求线程池。

### 13. `POST /skills/parse` 没有请求体上限
- `app/api/v1/skills.py:52`：`text: str = Field(min_length=1)` —— 无 `max_length`
- 对照 `SkillIn.content` 有 64KB 上限、`SkillImportIn` 却没有
- **会出事的场景**：传 100MB 文本，`skill_import._FRONTMATTER`（`re.DOTALL`，`skill_import.py:27`）在全串上做非贪婪匹配 + `splitlines`，单请求就能吃满 CPU 与内存。这是唯一不需要登录后权限之外成本的入口。
- **建议**：加 `max_length`（如 1MB），与 `CONTENT_MAX_BYTES` 同口径。

### 14. 文档删除不删对象存储，创建失败留孤儿对象
- `app/services/kb_service.py:344-348`（`delete_document` 只 `db.delete(doc)`）
- `app/services/kb_service.py:286`（先 `upload_file` 再 `db.add`）
- **会出事的场景**：(a) 删一篇 40MB 文档后，MinIO 里的对象永久残留，桶只增不减；(b) `upload_file` 成功但后续 `db.flush` 失败（外键/约束），对象立即成为孤儿。对比 `skill_service.delete_skill` 是显式清对象的，知识库这条路径漏了。
- **建议**：`delete_document` / `delete_kb` 一并删对象（先删对象失败只记 WARN 也可，至少不要静默永久泄漏）。

---

## P2：性能 / 体验 / 可维护性

### 15. `/stats/overview` 一次请求 ~20 次 DB 往返，且 `stuck_running` 走全表扫
- `app/services/stats_service.py:200-229`：12 个独立 `count` + `period_summary(1)` + `period_summary(7)` + `get_system_status`（内部还 ping Redis、探 DB、读调度器）
- `:223`：`Run.status == "running" AND started_at < now-1h` 没有复合索引（`models.py:357-359` 只有 source/api_key_id/share_id + started_at 的组合）
- **会出事的场景**：工作台首页每次刷新打 ~20 次查询；runs 表到百万行时 `stuck_running` 是顺序扫。
- **建议**：count 合成一条 `select ... filter` 的聚合；补 `(status, started_at)` 索引。

### 16. 每个 API Key 请求都在鉴权阶段写一次库并 commit
- `app/services/api_key_service.py:63-71`：`UPDATE ... SET used = used + 1` + `db.commit()`
- **会出事的场景**：(a) 每个 Key 请求一次写事务，QPS 高时写成为瓶颈；(b) `commit()` 会 expire 掉同一 session 里已加载的 `user` 对象，后续 `user.role` / `user.id` 访问触发额外 SELECT（每次 API Key 请求多一次查询）。
- **建议**：配额扣减改批量/异步（如每 N 次落一次，或 Redis 计数 + 定期落库）；`commit` 后显式 `db.refresh(user)` 或改用 `session.expire_on_commit=False`。

### 17. 读状态接口会顺手启动调度器线程
- `app/services/system_service.py:42`：`sched = get_scheduler()`
- `app/core/scheduler.py:105-107`：`get_scheduler()` 首次调用会 `BackgroundScheduler().start()` 并注册全部任务
- **会出事的场景**：`GET /system/status` 或 `GET /stats/overview`（内部调 `get_system_status`）是只读接口，却会在第一次被调用时启动调度线程、把 DB 里所有启用任务注册进来。测试里是隐藏副作用（本该由 lifespan 控制）；如果哪天要「关掉调度器跑单进程」，一个探活请求就会把它拉起来。
- **建议**：拆成 `peek_scheduler()`（只读已启动的实例，未启动返回 None）与 `get_scheduler()`（启动），状态接口用前者。

### 18. 内置 `http_request` 与工具行白名单的「空名单」语义相反
- `app/tools/general.py:200-215`：白名单为空 → **只拦内网、放行公网**（docstring 明说「让工具开箱可用」）
- `app/tools/permission.py:71-75`：白名单为空 → **一律拒绝**
- **会出事的场景**：管理员从工具行学到「没配白名单 = 拒绝」，给智能体挂上内置 `http_request` 后以为同样被锁，实际放行全部公网地址（含任意公网 SSRF 跳板）。这不是 bug 而是两套设计，但**没有文档把差异写出来**，且两者共用 `allowed_hosts` 这个键名。
- **建议**：文档（`docs/06` 第 7 节）明确两条路径的差异；或把内置工具的默认值改成「空 = 拒绝」以统一语义。

### 19. `_check_allowed_hosts` 的类型分支顺序会让错误信息误导
- `app/services/tool_service.py:120`：`if hosts in (None, []): return`
- **会出事的场景**：前端传 `""`（字符串）或 `[""]` 时不会命中这个提前返回，而是走到 `:124` 的 `not isinstance(hosts, list)` → 400「allowed_hosts 必须是数组」，而使用者填的是空串。提示与真实情况不符。
- **建议**：先判类型再判空；`""` 与 `[]` 同等对待。

### 20. 技能资源上限检查用 `strip()` 比较，与 `normpath` 后的实际名不一致
- `app/api/v1/skills.py:148`：`all(r.get("name") != name.strip() for r in existing)`
- `app/services/skill_resource.py:46-51`：`_safe_resource_name` 还会做 `posixpath.normpath`
- **会出事的场景**：已有 20 个资源时传 `scripts//add.py`：`name.strip()` = `scripts//add.py`，与已有的 `scripts/add.py` 不相等 → 通过上限检查 → `store_file` 归一成 `scripts/add.py` → `resources` 里出现两条同名条目（后者覆盖前者但条数仍 +1，上限被绕过）。
- **建议**：比较前先调 `skill_resource._safe_resource_name(name)`，与落库口径一致。

### 21. MCP 同步：远端工具数被截断时，被截掉的工具会被误标「来源已消失」
- `app/mcp/client.py:38`：`MAX_REMOTE_TOOLS = 100`，`:218` 只取前 100 个
- `app/services/mcp_service.py:377-385`：`for remote_name, row in existing.items(): if remote_name not in seen` → 标 `source_missing` 并停用
- **会出事的场景**：远端有 120 个工具时，第 101～120 个每次同步都被判「远端已删除」并停用；使用者重新启用，下次同步又被停用，来回拉锯，且工具页显示「来源已消失」是假信息。
- **建议**：截断发生时不要执行「远端消失」的判定（或返回 `truncated=True` 让调用方跳过这段），并在响应里告诉用户「远端工具数超过 100，只同步了前 100 个」。

### 22. 摘要刷新失败只记日志，边界不动，但没有任何状态出口
- `app/services/chat_service.py:127-128`：`if not new_summary: return False`
- **会出事的场景**：模型长期不可用时，`summary_upto_message_id` 永远不前进，每轮都注入 `SUMMARY_FALLBACK_CHARS=2000` 的截断原文——检索/对话质量持续下降，而 `/system/status` 上看不到任何异常（熔断器可能一直是 closed，因为摘要调用是单独的 invoke）。这正是规范 06 第 13.3 节说的「静默降级是本项目最贵的缺陷类型」。
- **建议**：把「最近一次摘要失败」接进 `system_service.get_system_status` 的 degraded 列表。

### 23. `list_resources` 每次打开技能详情都列一次对象存储
- `app/services/skill_resource.py:129-133`：`minio_client.list_objects(f"{OBJECT_PREFIX}/{skill_id}/")`
- **会出事的场景**：对象存储慢（跨公网 200ms）时，技能详情页每次刷新多一次往返；技能列表页如果逐个调用（当前没有，但接口是现成的）会退化成正 N 次 IO。
- **建议**：可接受现状，但值得在技能详情接口里标注「会访问对象存储」，或加短 TTL 缓存。

### 24. `_read_limited` 在超限时已经读进了 limit+1 字节才报错
- `app/api/v1/kb.py:170-177`、`app/api/v1/skills.py:59-66`
- **会出事的场景**：问题不大（有界），但注释写「不会先整块读进内存再判断」，实际是「读到超限那一刻才停」——与注释措辞相符，仅记录，不算缺陷。

---

## 已核查为「合规」的项（避免后续重复审）

| 检查项 | 结论 |
|---|---|
| api 层直接查库 / 拼 SQL | 0 处 |
| 裸 `except:` / `except BaseException` | 0 处 |
| `except Exception` 后无日志 | 0 处（`core/batch.py:51`、`core/scheduler.py:76/83`、`services/mcp_service.py:432` 都有 `logger.exception` 或明确降级说明） |
| 排序注入 | 全部走 `apply_sort` 白名单 |
| 时间区间 | 全部走 `time_range`（校验带时区、左闭右开） |
| 批量接口 | 全部走 `core.batch.run_batch`，逐条 rollback + 逐条返回 |
| 密钥进日志 | 未发现；`tools/executor.py:198/202` 有 `_scrub` 打码，`auth_service` / `api_key_service` 只记前缀与类型 |
| 运行记录入口 | 全部走 `run_service.create_run / finalize_run`，未发现自建 `Run(...)` |
| `app/workflow` / `app/runtime` 反向依赖 services | 0 处（`grep "from app.services" app/workflow app/runtime` 为空） |
| 会话归属 | 全仓只在 `conversation_service.owns` / `_owned_filter` 一处判定，无散落的 `user_id ==` |
| 分享访客数据结构 | 走 `share_service` 专用序列化，未复用内部结构 |
| 令牌用途隔离 | 访客令牌带 `typ=share_guest`，`get_current_user` 拒收带 typ 的令牌 |
| 每个路由的鉴权 | 逐个核对 22 个路由文件：除 `/health`、`/auth/login`、`/public/shares/*` 外均有 `require_roles` 或 `get_current_user`；`/public/shares/*` 有按「分享 + IP」限流 |

---

## 修复优先级建议

1. 第 1 条（白名单通配）+ 第 3 条（删除顺序）+ 第 2 条（audit 事务）—— 都是「静默失效 / 数据错」，且改动小。
2. 第 5、6、7 条 —— 会 500 或打爆资源，影响面明确。
3. 第 8、9、11、12 条 —— 并发与内存，需要在有压测的环境验证。
4. 其余按模块排期。
