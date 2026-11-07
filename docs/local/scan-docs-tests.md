# 测试覆盖缺口 + 契约文档漂移 审计

扫描日期 2026-11-08 · 范围 `agent-platform` · **纯只读静态扫描，未改代码、未跑 pytest**
基线：`backend/app` 108 个 .py（其中 94 个非 `__init__` 模块）/ `backend/tests` 57 个 `test_*.py` / 573 个测试函数

> 方法说明：覆盖判定用三重信号，任一命中即算"有测试" ——
> ① 测试文件 AST import 该模块；② 测试正文出现该模块公共函数名；③ 测试正文出现该路由的静态路径段（同一行内按顺序出现，避开 helper 拼 URL 的假阴性）。
> 这是**静态近似**，不等于行覆盖率。标注「疑似未覆盖」的条目建议先跑 `pytest --cov` 复核再立项。

> ⚠️ **行号会漂移**：扫描期间有其它会话在并发修改 `docs/03`、`docs/04`、`docs/09`（向量模型相关）。
> 本文行号以扫描时刻（2026-11-08 01:xx）为准，关键处同时给了**章节标题**，按标题检索比按行号可靠。
> 报告写完后复核过一次：`01/02/03/04` 的 MCP 命中数仍为 **0**，`09:75` 仍写着「接入 MCP」，结论不受并发编辑影响。

---

# A. 测试覆盖缺口

## A1. 有实现、零测试的模块（37 个）

按行数降序。判定为「测试文件里既没有 import、也没有任何符号/路由字符串引用」。

### 优先级 P0：零测试且承载核心业务规则（补用例前先补，出事静默）

| 模块 | 行数 | 缺哪类用例 | 建议条数 |
|---|---|---|---|
| `app/services/workflow_service.py` | 263 | 18 个函数全部零引用。工作流 CRUD、复制、批量、参数声明、`execute_workflow`、`resume_workflow`、`test_run_workflow` 只有经由路由的间接覆盖，服务层分支（图非法 400、被引用删除 409、复制命名"副本"、中断值提取 `_interrupt_value`）没有直接断言 | 8～10 |
| `app/services/api_key_service.py` | 262 | 16 个函数零引用。`hash_key` / `authenticate`（Key 有效 → 账号可用 → IP 白名单 → 限流 → 原子扣配额五步）、`_check_scope` 越权判定、`_ip_allowed` CIDR、`_get_owned` 归属隔离、`_owner_for` 代发。鉴权链路是安全边界，目前只有端到端 Smoke | 10～12 |
| `app/services/stats_service.py` | 238 | `period_summary` / `daily_runs` / `model_usage` / `agent_usage` / `workflow_usage` 全部零引用；`_clamp_days` 边界、`_tz` 时区切天、空窗口补零无断言 | 6～8 |
| `app/services/auth_service.py` | 178 | `login_guard_status` / `logout_others` / `login_history` / `change_password` / `mask_phone` 零引用。登录锁定 5 次 / 10 分钟、锁定期间 Redis 故障降级、手机号脱敏边界（< 8 位全遮）都没有直接测 | 6～8 |
| `app/services/prompt_template_service.py` | 178 | 版本快照、回滚 version+1、`unused_variables`、`prompt_template_outdated` 一次 IN 批量算，全是易错点 | 5～7 |
| `app/services/model_service.py` | 165 | 被引用不可删的判定、`agents_count` 口径（草稿 + 线上版本） | 4～5 |
| `app/services/schedule_service.py` | 146 | `run_now` / `toggle_schedule` / `_check_workflow` / `_last_runs` 零引用；创建人停用时留失败运行的分支在别处测过，服务层自身无断言 | 5～6 |
| `app/services/skill_import.py` | 128 | `parse_frontmatter` / `parse_skill_md` / `to_skill` 零引用。SKILL.md 解析是本模块最易出格式兼容问题的地方（`_unquote` 引号处理） | 5～6 |
| `app/rag/parser.py` | 126 | `parse_text` / `parse_markdown` / `parse_pdf` / `parse_docx` / `parse_table` / `parse_image` **全部零引用**。各类型解析分片规则（PDF 按页、Word 保留标题、CSV/XLSX 保留列名）没有任何直接断言，只在 `test_pipeline_table` 里被间接经过 | 6～8 |
| `app/rag/minio_client.py` | 109 | `get_minio` 零引用；对象不存在、连接失败的分支无断言 | 3～4 |

### 优先级 P1：零测试的工具/核心辅助层

| 模块 | 行数 | 缺哪类用例 | 建议条数 |
|---|---|---|---|
| `app/core/ip_filter.py` | 72 | `is_denied` / `_parse_networks` / `__call__` 零引用。IP 黑名单是安全边界，CIDR 解析错误会静默放行或误拦；`/health` 豁免无断言 | 4～5 |
| `app/core/pagination.py` | 98 | `page_params` / `sort_params` / `apply_sort` / `time_range` / `paginate` / `offset` 零引用。排序白名单（防注入）、`page_size` 上限 100、时间区间时区处理全是纯函数，最该单测 | 5～6 |
| `app/core/batch.py` | 55 | `run_batch` / `unique_ids` 零引用。批量去重、逐条独立执行、失败清单聚合 | 3～4 |
| `app/services/chat_turn.py` | 146 | `open_turn` / `validate_message` / `resume_conversation` / `target_of` / `_replay_of` 零引用。消息幂等回放（client_message_id 不重复落库不重复计费）是已上线的承诺 | 5～6 |
| `app/services/chat_trace.py` | 55 | `make_step` / `retrieve_step` / `successor` / `stop` / `elapsed_ms` 纯函数零引用 | 2～3 |
| `app/core/audit.py` + `app/services/audit_service.py` | 27 + 34 | `record_audit` / `list_audit_logs` 零引用。审计字段过滤、凭据只记"已更换"的脱敏规则无直接断言 | 3～4 |
| `app/api/v1/audit.py` | 33 | 审计查询路由的筛选（动作 / 资源 / 用户名 / 时间区间） | 2～3 |
| `app/core/limits.py` / `app/db/base.py` | 12 / 5 | 常量与声明基类，可不补 | 0 |

## A2. 端点级缺口（154 个路由中确认为 8 个未覆盖）

用 f-string 占位符正则二次校验后，确认以下 8 个路由在测试里**没有任何调用**：

| 路由 | 所在文件 | 说明 |
|---|---|---|
| `POST /agents/batch` | `api/v1/agents.py:55` | 智能体批量启停 / 删除。同类 `/tools/batch`、`/models/batch`、`/kb/batch` 都有测试，唯独 agents 没有 |
| `POST /mcp-servers/batch` | `api/v1/mcp_servers.py:76` | MCP 批量（enable / disable / delete） |
| `POST /mcp-servers/test` | `api/v1/mcp_servers.py:88` | 测试连接（不落库路径，且要能复用已存凭据） |
| `POST /mcp-servers/{id}/toggle` | `api/v1/mcp_servers.py:106` | **停用服务器要级联停用它同步出的全部工具** —— 这是静默失效类逻辑，最该测 |
| `POST /embedding-models/batch` | `api/v1/embedding_models.py:75` | 向量模型批量 |
| `POST /embedding-models/{id}/test` | `api/v1/embedding_models.py:110` | 真发一条 embeddings 请求并核对维度 |
| `GET /skills/stats` | `api/v1/skills.py:84` | `{total, enabled}` |
| `POST /skills/batch` | `api/v1/skills.py:96` | 仍被智能体绑定的进失败清单 |

另有 4 个路由**只在辅助函数或列表里出现过一次**，建议补正向断言：
`GET /workflows/{id}/runs`（`list_workflow_runs` 分页 / 状态过滤 / 时间区间）、
`POST /agents/{id}/share/reset`、`POST /schedules/{id}/run`、`GET /stats/runs/summary`。

> 其余 146 个路由均有直接调用。*`public_shares` 的 5 个路由通过 `_pub(code, tail)` helper 拼接，静态扫描报"未覆盖"属假阴性，实际 `test_shares.py` 覆盖得很密（22 处 4xx/5xx 断言）。*

## A3. MCP 客户端层：**没有任何真实协议验证**（最高优先）

`app/mcp/client.py`（183 行）是唯一与外部 MCP 服务器打交道的模块，但 `tests/test_mcp.py` 在文件头就写明「MCP 客户端那一层整体打桩（probe / call）」。

**被完全打桩、零测试的函数**：

| 函数 | 行号 | 风险 |
|---|---|---|
| `_auth_headers` | L50 | 凭据拼 `Authorization: Bearer`。拼错 = 所有 MCP 调用 401，且错误来自远端，看不出是本地问题 |
| `_Session.__aenter__` | L69 | **http / sse 两种传输的分支**。`streamable_http_client` 没有 headers 参数、必须经 `create_mcp_http_client` 建 client（SDK 换用 httpx2），这行注释本身就是踩过的坑 |
| `_Session.__aexit__` | L96 | 清理失败只记日志，不盖掉调用结果 |
| `_wrap_error` | L108 | **ExceptionGroup 拆包**取根因。拆错会把一条清晰的 401 报成 `ExceptionGroup` |
| `_content_to_text` | L144 | text / image / resource 三类内容分别处理，`MAX_RESULT_CHARS=100000` 截断。图片不展开是有意设计（防撑爆上下文） |
| `probe` / `call` | L120 / L169 | 已打桩，真实实现只经过 SDK，无本地断言 |

**建议补法（不需要真服务器）**：
1. 用 `httpx.MockTransport` 或起一个进程内的 `http.server`，喂标准 MCP JSON-RPC 帧（`initialize` → `tools/list` → `tools/call`），验证 `probe` 能解析出 `McpTool`、`call` 能正确取 `content`。**3 条**
2. `_content_to_text` 的纯函数单测：text / image / resource / 未知 type / 超长截断。**1 条**（纯函数，最便宜）
3. `_wrap_error` 的 ExceptionGroup 拆包单测。**1 条**
4. `_auth_headers`：有 secret / 无 secret / 覆盖同名头。**1 条**
5. `_Session` 的 http 与 sse 分支各一条（可用 monkeypatch 替换 SDK 的 `sse_client` / `streamable_http_client`，只验参数传递与 AsyncExitStack 清理）。**2 条**

合计约 8 条，能把当前"零协议验证"降到"边界明确"。

## A4. 只测 happy path 的关键接口

按测试文件的 4xx/5xx 断言密度排序（低 = 负向覆盖薄）。以下挑出**关键 7 个**：

| 接口 / 模块 | 现状 | 缺什么 | 建议 |
|---|---|---|---|
| `POST /workflows/{id}/resume` | 仅 1 处（`test_api_key_scopes.py:223` 作为 lambda 出现） | 非 awaiting_review 状态续跑、decision 非法、非本 Key 发起的运行、工作流已删 | 4 |
| `GET /workflows/{id}/runs` | 0 处直接断言 | 分页、status 过滤、started_from/to 时区区间、排序白名单 | 3 |
| `POST /schedules/{id}/run` | 0 处 | 立即执行落运行记录、工作流已停用、创建人已停用 | 3 |
| `GET /stats/runs/summary` | 0 处 | 空库返回零值而非报错、P50/P95 边界、筛选联动 | 3 |
| `app/api/v1/stats.py` 整体 | 5 个服务函数零引用 | 时区切天、缺失日期补零 | 4 |
| `app/workflow/validation.py` | 仅 `test_workflow_parallel` 间接 | 六条结构规则逐条负向（每条应有一条 400 用例） | 6 |
| `app/tools/executor.py` `_auth_parts` / `_scrub` | `test_tool_secrets` 有覆盖但未覆盖解密失败 | `AES_KEY` 换过导致 `InvalidToken` 时返回可读错误而非 500 | 2 |

**整体判断**：`test_sse_heartbeat`(0)、`test_migrations_tools`(0)、`test_workflows`(0)、`test_models`(0)、`test_db_utils`(0)、`test_http_client`(0)、`test_chat_reasoning_persist`(0)、`test_reasoning`(0)、`test_tools`(0)、`test_tool_secrets`(0)、`test_cleanup`(0)、`test_deploy_prereq`(0)、`test_rerank`(0)、`test_runs`(0)、`test_chat_summary`(0)、`test_chat_events`(0)、`test_sandbox`(0)、`test_tool_permission`(0) —— 这 18 个文件**没有任何 4xx/5xx 状态码断言**。其中 `test_sandbox` 是纯函数风格可接受，但 `test_tools` / `test_tool_secrets` / `test_runs` 是走路由的，缺负向就是缺口。

---

# B. 契约文档漂移

对比基线：`app/db/models.py`、`app/api/v1/*.py`、`app/schemas/__init__.py`。
每处给「文档行号 + 现状 + 应改成什么」。

## B1. `docs/01-需求说明.md`（V2.26 · 2026-10-05）

### 漂移 1：完全没有 MCP 连接器 —— 最高优先

**证据**：全文 `grep -i mcp` **零命中**。而代码侧有 `app/mcp/client.py`(183行)、`app/services/mcp_service.py`(460行)、`app/api/v1/mcp_servers.py`(125行, 9 个路由)、`mcp_servers` 表、迁移 `20261107_100000_mcp_servers.py`、`tools.type` 新增 `mcp`。

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L26 术语表「工具 Tool」 | 「智能体或工作流可调用的外部能力：**内置工具或自定义 HTTP 接口**」 | 改为「内置工具、自定义 HTTP 接口，或经 MCP 连接器同步的外部工具」 |
| L28 附近（术语表末尾） | 无 MCP 条目 | 新增术语行：**MCP 连接器 McpServer｜登记一个外部 MCP 服务器（http / sse 两种传输，不支持 stdio），同步它暴露的工具清单；同步出的工具默认停用，由人看过再启用；删服务器不删工具，只全部停用** |
| §4.5 工作流（L110-118）之后 | 无「工具与连接器」小节，`FR-014 工具管理`(L117) 只有一句「工具的增删改查与测试调用」 | 新增 **FR-048｜MCP 连接器｜P1｜已实现｜** 条目，写清：登记/编辑/删除服务器；`allowed_hosts` 必填（空名单 400，与 HTTP 工具的"空名单放行"不同）；凭据加密存 `secret_enc`、任何接口只回 `has_secret`；同步语义三种情况（远端有/库里有/远端消失 → 新建默认停用、更新描述与参数声明、消失的停用不删除）；嵌套参数降级成文本并在调用前还原；停用服务器级联停用其全部工具；删服务器保留工具只停用（避免破坏 `agents.tool_ids`）；stdio 一律不做（等于执行配置里写的任意命令） |
| L117 `FR-014` | 「工具的增删改查与测试调用」 | 补一句「`type` 取值 builtin / http / mcp；mcp 类型的工具由连接器同步生成，不能经工具接口编辑（`PUT /tools/{id}` 对 mcp 返回 400）」 |

### 漂移 2：技能（Skill）只有 NFR 里的一句旁证

**证据**：全文提到"技能"**只有 L157 NFR-002** 的「代码执行节点与技能脚本改走子进程沙箱」——这是在讲沙箱，不是讲技能功能。而代码侧有 `skills` 表、`app/services/skill_service.py`(229) + `skill_import.py`(128) + `skill_resource.py`(145)、`app/api/v1/skills.py`(192, 11 个路由)、`agents.skill_ids`、内置工具 `load_skill`、迁移 `20261105_203000_skill_table.py`。

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L26 术语表 | 无技能条目 | 新增：**技能 Skill｜「操作手册」型知识。与提示词模板分工不同：模板是人设（保存时渲染进 `system_prompt`，一变就升版本）；技能只把 `name + description` 放进系统提示的「可用技能」目录，模型需要时调内置工具 `load_skill(name)` 取正文。`always_on` 为真的正文常驻注入** |
| §4.2 模型与智能体（L81-90） | 无技能 FR | 新增 **FR-049｜技能管理｜P1｜已实现｜**：技能的 CRUD、`name` 格式 `^[a-z0-9]+(-[a-z0-9]+)*$` 且 ≤ 64、`description` 必填（空描述 = 永不加载）、`content` 按 UTF-8 字节限 64KB、`version` 在 content/description 变化时 +1 不保留快照、`always_on`、资源文件（只收 `.py`、单个 512KB、最多 20 个）、SKILL.md 解析导入、仍被智能体绑定的删除 409 |
| §4.5 `FR-014` 附近 | — | 补一句：`load_skill` **必须白名单** —— 只能读本次装配的 `agents.skill_ids`，传别的名字返回「技能不存在」，且不区分"不存在"与"没绑定"（区分了等于告诉模型哪些技能存在但读不到）；没绑技能时不暴露这个工具 |
| §4.2 `FR-005` 智能体配置（L88） | 「名称、描述、系统提示词、模型、参数、知识库列表、工具列表」 | 补「技能列表（`skill_ids`，≤ 20）」；快照字段列表补 `skill_ids` |

### 漂移 3：权限矩阵缺两行

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L52「工具、知识库、工作流」 | developer ✓ / caller ✗ | 拆出或新增一行 **「MCP 连接器（管理接口，API Key 亦 403）」｜admin ✓｜developer ✓｜caller ✗**。核实依据：`mcp_servers.py:3` 注释「仅允许 admin / developer，不接受 API Key」，`test_mcp.py:165 test_caller_cannot_manage` 断言 caller 403 |
| L53 附近（提示词模板那行之后） | 无技能行 | 新增 **「技能」｜admin ✓｜developer ✓｜caller ✗（API Key 亦 403）**。核实依据：`04` L461 已写 `/skills` 是 AD + API Key 403 |

### 漂移 4：内置工具清单过期

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L99 `FR-008` | 「内置工具：当前时间、四则计算器」 | 实际有 **10 个**：`current_time` / `calculator`（BASIC，总是可用）+ `text_stats` / `random_int` / `random_choice` / `base64_encode` / `base64_decode` / `json_query` / `http_request` / `web_search`（`OPTIONAL_BUILTIN_TOOLS`，工具页可勾选挂到智能体）+ `load_skill`（技能装配时按需暴露）。核实依据 `app/tools/builtin.py:92-95`。另需补「能力型内置工具各有自己的配置（`tools.config` + `secret_enc`），配置项声明在 `app/tools/tool_config.py`，不落库」 |

### 漂移 5：版本记录停在 V2.29

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L3 版本行 | `版本 V2.26 · 2026-10-05` | 与 L223 最后一条记录（V2.29）不一致，自身就漂了。应为 **V2.30 · 2026-11-08** |
| L223 之后 | 最后一条是 V2.29（2026-10-05） | 补 `V2.30 / V2.31 / V2.32` 三条：技能（`17` §4）、MCP 连接器（`17` §5）、向量模型表（`/embedding-models`，2026-11-08） |

### 漂移 6：正文引用了 8 个未定义的 FR 编号

L89/L91/L96/L97 等正文里引用了 **FR-039 / FR-040 / FR-041 / FR-042 / FR-043 / FR-044 / FR-046 / FR-047**，但需求表里都没有对应条目（只定义了 FR-001~038 + FR-045）。要么补条目，要么改成纯文字描述。核实：`grep '^| FR-' ` 只收出 39 个编号。

---

## B2. `docs/03-数据库设计.md`（V2.3 · 2026-11-05）

### 漂移 1：`mcp_servers` 表完全缺失

**证据**：全文 `grep -i mcp` 零命中。模型在 `app/db/models.py:143-169`，迁移 `20261107_100000_mcp_servers.py`。

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| §2 表关系概览（L21-33 代码块） | 无 mcp_servers | 在 `skills` 那行后加 `mcp_servers（独立表）─< tools（tools.mcp_server_id 无外键，服务器删了工具保留）` |
| §3.21 skills 之后（L395 附近） | — | **新增 §3.22 mcp_servers 外部 MCP 服务器**，按 `models.py:143-169` 逐列写：`id` bigint PK / `name` varchar(64) 非空唯一 / `description` text 可空 / `transport` varchar(16) 非空默认 `http`（http = Streamable HTTP，sse = 旧版 HTTP+SSE）/ `url` varchar(512) 非空 / `headers` jsonb 非空默认 `{}`（非敏感头，含凭据键保存时 422）/ `secret_enc` text 可空（凭据密文，任何接口只回 `has_secret`）/ `is_enabled` boolean 非空默认 true 索引 / `allowed_hosts` jsonb 非空默认 `[]`（出站白名单，**空值即拒绝**，与 tools 的"空名单放行"不同）/ `last_synced_at` timestamptz 可空 / `last_error` text 可空 / `created_by` bigint FK users SET NULL / `created_at` / `updated_at` |
| 同上 | — | 补一段说明：**stdio 不做**（等于在服务器上执行配置里写的任意命令，同类问题见 MaxKB CVE-2026-39417）；删服务器不删工具，`tools.mcp_server_id` 故意**不设外键**（与服务器生命周期解耦，避免破坏 `agents.tool_ids`）；保留期由服务层统一停用 |

### 漂移 2：`tools` 表缺 3 个 mcp 相关列 + type 取值过期

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L111 `tools.type` | 「非空 | **builtin / http**」 | 「非空 | **builtin / http / mcp**」 |
| L118（`created_at` 之后、L120 说明之前） | 只有到 `created_by` / `created_at, updated_at` | 补 3 列：`mcp_server_id` bigint 可空（**不设外键**，原因见上）/ `remote_name` varchar(128) 可空（远端工具原名，本地名是 `{服务器名}_{远端名}` 清洗后） |
| L120 | 「内置工具（`current_time`、`calculator`）由代码提供……`type` 为 builtin 的行只是登记」 | 补：`type='mcp'` 的行由连接器同步生成，`config` 里存 `{allowed_hosts, url, transport, parameters, degraded_params, source_deleted?}`，**不能经`PUT /tools`编辑**（返回 400）；`source_deleted=true` 表示所属服务器已删、工具仅停用保留 |
| L487 §5 状态码汇总 | 「`tools.type` | builtin / http」 | 改 `builtin / http / mcp` |
| §6 索引（L491-509） | 无 mcp 相关 | 补 `mcp_servers`：`name`（唯一）、`is_enabled`；`tools`：`mcp_server_id`（服务层按它查"这个服务器同步出了哪些工具"） |

### 漂移 3：`embedding_models` 表缺失（连带 4.6 指向不存在的小节）

**证据**：全文只有 L129 一处 FK 提及。模型在 `models.py:206`，迁移 `20261108_010000_w8k2mn_embedding_models.py`。而且 `04` L179 明确写着「见 `03` 4.6」——但 03 的 §4 只有 4.1~4.5，**4.6 不存在**。

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| §3.2 models 之后 | — | 新增 **§3.2b embedding_models 向量模型**：`id` / `name` varchar(128) 非空 / `provider` varchar(32) 非空索引 / `api_base` / `model_name` / `api_key_enc` / `dim` integer 非空（**必须等于 `document_chunks.embedding` 列宽 1024**）/ `request_size` integer 默认 20 / `is_enabled` boolean 索引 / `created_by` / 时间列 |
| §4 之后 | 无 4.6 | 新增 **§4.6 向量维度约束**：`document_chunks.embedding` 是定长 `vector(1024)`，pgvector 一列一个维度，所以当前只能选产出 1024 维的模型；要混用其他维度需加列或分表。**这一节被 `04` L179 引用，必须补上** |
| §2 表关系概览 | `knowledge_bases` 未连出 | 加 `embedding_models ─< knowledge_bases（embedding_model_id，RESTRICT）` |
| L129 `embedding_model_id` | 已写对 | 无需改，但应在 §3.2b 里回指 |
| §7 迁移表（L543 之后） | 最后一条是 `20261105_203000_skill_table.py` | 补 6 条：`20261105_150000_wf04_start_variables` / `20261105_190000_conversation_kind` / `20261105_193000_message_reasoning` / `20261105_204500_agent_version_skill_ids` / `20261106_020000_builtin_general_tools` / `20261107_100000_mcp_servers` / `20261108_010000_w8k2mn_embedding_models` |

### 漂移 4：`tools.config` 的 JSON 结构只写了 http

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| §4.2 标题（L409） | 「`tools.config`（**http**）」 | 改「`tools.config`（http / mcp）」，并加 mcp 的示例：`{"allowed_hosts": ["mcp.example.com"], "url": "...", "transport": "http", "parameters": {...}, "degraded_params": ["tags"]}`。补一句：`degraded_params` 记的是被降级成文本的数组/对象参数，**转发前必须按 JSON 解析还原**，否则远端收到字符串、报错来自远端看不出是本地转换的问题 |

### 漂移 5：§8 注意事项可补一条

「**向量模型换了等于切片全废**」：`knowledge_bases.embedding_model_id` 建库时定、之后不可改（RESTRICT），换模型只能删库重建；`EMBEDDING_DIM` 与列宽不一致时入库直接报错。

---

## B3. `docs/04-接口设计.md`（V2.4 · 2026-11-06）

### 漂移 1：完全没有 `/mcp-servers` 一节

**证据**：全文 `grep -i mcp` 零命中。路由 9 个，见 `app/api/v1/mcp_servers.py`。

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L461 `### 4.20 技能` 之后（或 4.16 前后，按现有编号习惯） | 无 | **新增一整节 `### 4.21 MCP 连接器 /mcp-servers（AD；API Key 403；2026-11-07 起，17 §5）`**，格式照 4.20 技能。逐条写： |

新增节的接口清单（照 `mcp_servers.py` 的路由顺序，注意 **`/test` 固定路径必须声明在 `/{server_id}` 之前**）：

| 方法 路径 | 角色 | 请求 | 响应 / 说明 |
|---|---|---|---|
| GET /mcp-servers | AD | 分页参数；`q` 名称或描述模糊；sort | 分页信封，items 带 `tools_count` / `created_by_username`；**凭据只回 `has_secret`** |
| POST /mcp-servers | AD | `{name(1-64), description?, transport: http\|sse = http, url(1-512), headers={}, secret?, clear_secret=false, is_enabled=true, allowed_hosts}` | 409 重名；400 地址非法 / **白名单为空** / 请求头里写了凭据 |
| POST /mcp-servers/batch | AD | `{ids, action: enable / disable / delete}` | 批量信封 |
| POST /mcp-servers/test | AD | `McpServerIn + server_id?` | **不落库**；连一次取工具清单，返回条数与名字；传 `server_id` 且没重填凭据时用已存的 |
| GET /mcp-servers/{id} | AD | | 服务器对象 + `tools: [{id, name, remote_name, is_enabled, ...}]` |
| PUT /mcp-servers/{id} | AD | 同 POST（整体覆盖）；`secret` 不传沿用、传了更换、`clear_secret` 清除 | 服务器对象 |
| POST /mcp-servers/{id}/toggle | AD | | `{id, is_enabled}`；**停用会同时停用它同步出的全部工具**（地址与凭据都在服务器行上） |
| POST /mcp-servers/{id}/sync | AD | | `{created, updated, disabled, total}`；新建默认停用、已有的更新描述与参数声明、**远端消失的停用不删除**；远端不可达 502 + 写 `last_error`；停用的服务器不能同步 400 |
| DELETE /mcp-servers/{id} | AD | | `{code:0}`；工具**保留但全部停用**，`config.source_deleted=true`（避免破坏 `agents.tool_ids`） |

另需在节内补三段说明：
1. **`allowed_hosts` 必填** —— 与 HTTP 工具不同，这里不给"空名单放行"的口子（MCP 地址由管理员配，没写白名单就无从判断目标是否可信）。
2. **参数降级与还原** —— 远端 inputSchema 里的嵌套对象 / 数组降级成 `string` 并在描述里追加"JSON 字符串"，同时记进 `config.degraded_params`；调用前按 JSON 解析还原，不是合法 JSON 时原样转发。
3. **stdio 不支持** —— 地址只接受 http / https，`stdio://` 400。

### 漂移 2：`/tools` 一节缺 mcp 类型

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L239 `GET /tools` 的 `type` 过滤 | 「`type` = **builtin / http**」 | 「`type` = **builtin / http / mcp**」 |
| L239 items 结构 | `[{id, name, description, type, config, timeout, is_enabled, agents_count, auth, created_by, created_by_username, updated_at}]` | 补三项：`mcp_server_id` / `remote_name` / `mcp_server_name`（工具页据此显示「MCP · 某某服务器」标签；对其它类型恒为 null） |
| L244 `PUT /tools/{id}` | 「同 POST，另加 `clear_secret=false`……」 | 补：**`type='mcp'` 的工具不允许经这里改，返回 400**「MCP 工具由「MCP 连接器」同步生成，不能在这里编辑；改地址与凭据请改服务器，更新参数请重新同步」。核实依据 `tool_service.py:207-208` |
| L243 `POST /tools` | `type="builtin"` | 补：`type` 取 builtin / http；mcp 不允许手工创建（由 sync 生成） |

### 漂移 3：技能节的小瑕疵（低优先）

L461-486 的 §4.20 内容本身准确，但**章节编号顺序错乱**：文件里 4.20 出现在 4.17（L521 运营统计）**之前**。建议把 4.20 挪到 4.19 之后，或整体重排编号。

---

## B4. `docs/02-架构设计.md`（V2.3 · 2026-09-06）

`grep -i 'mcp\|skill\|技能'` **零命中** —— 整份架构文档对这两个 2026-11 新增的大模块完全无感知。

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| §2.1 分层图（L21-33） | 应用层列「认证 用户 模型 智能体 对话 会话 工具 知识库 工作流 运行记录 审计 API Key 定时任务」 | 补 **技能、MCP 连接器**；模型那项可细分为「模型 / 向量模型」 |
| §2.1 能力层 | 「tools 工具执行器」 | 补 **`mcp` MCP 客户端（http / sse 传输，经官方 SDK，不做长连接池）** |
| §3.1 后端代码结构表（L50-65） | 无 `app/mcp/` 一行 | 新增行：`| \`app/mcp/\` | \`client\` MCP 客户端：http / sse 两种传输，每个入口"开一次会话、做完、关掉"（不做长连接池）；stdio 不做 | |` |
| 同上 | `app/tools/` 行只有 executor / schema / langchain_tools | 补 `builtin`（内置工具与参数声明）、`general`（能力型内置工具实现）、`tool_config`（各工具配置项声明）、`permission`（调用闸门） |
| 同上 | `app/services/*` 行未点名 | 可补 `mcp_service` / `skill_service` / `skill_import` / `skill_resource` 的职责一句话 |
| §4.5 工具（L228-233） | 只讲 builtin + http | 新增 **§4.5b MCP 连接器**：登记 → sync（三种情况语义）→ 参数降级与还原 → 执行分支（`executor` 按 `type='mcp'` 分发到 `mcp_service` → `mcp.client.call`）→ 闸门（`allowed_hosts` 必填、share 来源一律拒绝） |
| §4 核心链路 | 无技能 | 新增 **§4.x 技能装配**：`agent_config` 解析 `skill_ids` → `always_on` 的正文常驻注入 + 其余的 `name + description` 进目录 → 暴露 `load_skill` 内置工具（按 `skill_ids` 白名单） |
| §6 已知局限与演进（L303，全文只有一句「按优先级排列的改进项与已知问题见 `09-演进路线.md`」） | 本文件没有自己的已知局限清单，也没有变更记录表 | 补：MCP 首版不做长连接池（每次调用多一次握手 RTT）、不做 stdio；技能正文与提示词同口径不回传分享访客。变更记录可只写版本行 |
| L3 版本行 | `V2.3 · 2026-09-06` | 升版本（本文档无变更记录表，至少在版本行注明改了什么） |

---

## B5. `docs/09-演进路线.md`（V2.4 · 2026-09-06）

**漂移最严重的一处：「明确不做的事」里还写着"接入 MCP"。**

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L75 §5「明确不做的事」 | 「- **接入 MCP。**」 | **删掉这一条**。MCP 已于 2026-11-07 实现（`app/mcp/client.py` + `mcp_servers` 表 + 9 个路由 + `test_mcp.py` 22 条用例）。若仍想保留"不做 stdio"的边界，改成「- **接入 MCP 的 stdio 传输。** HTTP / SSE 已接（2026-11-07）」。这是**方向性矛盾**：文档说"不做"，代码已经在跑 |
| L73 例外清单 | 只列到页面与节点类型的例外 | 可补一条例外：技能与 MCP 连接器（`17` §4/§5）经使用者确认后实现 |
| §1-3 各梯队 | 无技能 / MCP | 相应条目状态改为已完成并写日期 |
| L3 版本行 | `V2.4 · 2026-09-06`，而 `09` 文件 mtime 是 2026-11-08 00:55 | 版本号与内容不同步，升版本 |

---

## B6. `docs/10-差距分析.md`（无版本行）

| 位置 | 现状 | 应改成什么 |
|---|---|---|
| L17 | 「不应为完整 6 层投入（不拆微服务、**不上 K8s、不接 MCP**）」 | 与 `09` 同一问题：MCP 已接。改为「不拆微服务、不上 K8s（MCP 连接器已于 2026-11 接入，见 `09` 修订）」 |
| L12 结论段 | 「17 张业务表无任何 tenant / org / project 字段」 | 实际表数已变（现 **24 张**，新增 `skills` / `mcp_servers` / `embedding_models` 等）。数字需重算 |
| L28-103 逐层对照 | 缺 MCP / 技能 / 向量模型三项能力 | 在第三层「AI 中台核心服务层」补这三项现状 |
| 全文 | 无版本行、无日期 | 补版本行（与其余文档一致） |

---

# C. 汇总：建议修复顺序

**文档（改动小、风险为零，可立即做）**
1. `09` L75 删掉「接入 MCP」—— 方向性矛盾，最刺眼
2. `10` L17 同上；L12 表数重算
3. `03` 补 `mcp_servers` 表 + `tools` 三列 + `type=mcp` + `embedding_models` + **§4.6**（别处已被引用）
4. `04` 新增 `/mcp-servers` 一节 + `/tools` 补 mcp
5. `01` 补 FR-048（MCP）/ FR-049（技能）+ 权限矩阵 2 行 + 术语 2 条 + 版本记录 + 修 8 个悬空 FR 引用
6. `02` 分层图、代码结构表、§4.5b、§4.x

**测试（按 ROI 排序）**
1. `app/mcp/client.py` 的 5 个零测试函数（`_content_to_text` / `_wrap_error` / `_auth_headers` 是纯函数，最便宜）—— 约 4 条
2. 端点缺口 8 个（其中 `/mcp-servers/{id}/toggle` 的级联停用最该补）—— 约 8 条
3. `api_key_service` 鉴权链路（安全边界零直接测试）—— 约 10 条
4. `core/ip_filter` + `core/pagination` + `core/batch`（纯函数，便宜且是安全/契约边界）—— 约 12 条
5. `rag/parser` 六种解析器（文档处理的核心，零直接断言）—— 约 6 条
