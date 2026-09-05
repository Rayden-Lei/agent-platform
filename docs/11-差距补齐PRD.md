# 智枢·智能体平台 差距补齐需求（PRD）

版本 V0.2 · 2026-09-05 · 状态：已按 `13-差距补齐评审报告.md` 修订

> 本文档把 `10-差距分析.md` 第 4 节的"短期 / 中期"建议写成可开发、可验收的功能需求。编号延续 `01-需求说明.md`（FR-025 起），01 的 4.7 节只保留一行摘要，本文档是这批需求的契约来源；每条实现后同批回写 01 的状态。
> "现状"一栏全部以 2026-09-05 的后端代码为准，写明文件位置，评审时可对照。
> 执行顺序、拆分与工作量见 `12-差距补齐开发计划.md`。

## 0. 结论先行

- **范围**：9 条需求，两档。短期 7 条（FR-025～FR-031）补入口治理与编排层空位；中期 2 条（FR-032、FR-033）布局检索质量与多业务线隔离。
- **不变的前提**：单体 + Docker Compose 的部署形态、三级角色、响应不套统一信封、契约演进一次切换不留兼容层。这些是 `02-架构设计.md` 第 5 节与 `09-演进路线.md` 第 5 节的既定决策，本批不动。
- **明确不做**：GPU / K8s、模型微调、资产市场、企业 SSO、租户级配额计量。理由见 `10-差距分析.md` 4.3。
- **最大的两个设计约束**：① 所有新增降级路径都必须按 `06-后端规范.md` 13.3 的三件事做到可见；② Prompt 模板与并行节点都不改对话运行时链路，风险收敛在编辑期。
- **评审决策**（2026-09-05，按 `13-差距补齐评审报告.md` 第 6 节的推荐项采纳）：① API Key 按创建人行级隔离，developer 可进 API Key 页；② 结构类校验在 schema 层报 422、需读库或跨字段语义的校验在服务层报 400；③ 模型 SDK 重试归零，`MODEL_HTTP_TIMEOUT` 保持 120 秒；④ FR-028 由 P0 降为 P1；⑤ `CORS_ORIGINS` 默认值维持本机前端地址。

## 1. 背景与目标

`10-差距分析.md` 的结论：平台是一套工程规范良好的私有化 MVP 底座，离企业级中台差在三类结构性能力。其中"入口治理"与"编排层生产力"两类可以在不改部署形态的前提下用较低成本补齐，且直接服务于 `09-演进路线.md` 第一梯队的目标"让它能被真实系统用起来"。

本批目标按优先级：

1. 外部系统经 API Key 调用时，平台能限速、能按来源 IP 拒绝、上游模型故障时能快速失败而不是拖满 120 秒超时。
2. 开发者能集中管理提示词并复用到多个智能体，能在工作流里并行跑多条分支，能让模型按结构化参数调用工具。
3. 长会话不再每轮重算摘要。
4. 为检索质量（Rerank）与多业务线隔离（轻量多租户）做好设计与触发条件，不空转。

## 2. 范围总表

| 编号 | 名称 | 档 | 优先级 | 对应差距（`10` 章节） | 依赖 |
|---|---|---|---|---|---|
| FR-025 | 入口限流 | 短期 | P0 | 2.3 统一 API 网关"无限流" | Redis（已有） |
| FR-026 | 来源 IP 管控 | 短期 | P0 | 2.3"无黑白名单" | 与 FR-025 共用取客户端 IP 的函数 |
| FR-027 | 模型调用熔断 | 短期 | P1 | 2.3"无熔断" | 无 |
| FR-028 | Prompt 模板管理 | 短期 | P1（评审前 P0；本批 P0 的判据是"接住真实调用方"，它不满足） | 2.2 Prompt 工程中心 ❌ | 无 |
| FR-029 | 工作流并行节点 | 短期 | P1 | 2.2"缺并行分支" | 引擎状态需先改为带 reducer（见 4.5.4） |
| FR-030 | 工具参数 schema | 短期 | P1 | 2.2 / `09` 第二梯队 | 无 |
| FR-031 | 对话摘要持久化 | 短期 | P1 | `09` 第二梯队 | 无 |
| FR-032 | Rerank 模型接入 | 中期 | P2 | 2.3 RAG"词法重排" | 已配置真实向量模型（否则候选质量差，Rerank 收益有限） |
| FR-033 | 轻量多租户骨架 | 中期 | P2 | 2.7 多租户 ❌ | 触发条件（见 4.9.1）；FR-028 新表也要带租户列，故排在其后 |

## 3. 角色与场景

角色沿用 `01-需求说明.md` 第 3 节的三级角色。本批新增接口的授权要求：

| 能力 | admin | developer | caller | API Key |
|---|---|---|---|---|
| 查看、编辑、启停、删除 API Key | ✓（全部 Key） | ✓（仅本人创建的 Key；页面对 developer 开放） | ✗ | ✗ |
| 查看熔断 / 限流状态（`/system/status`） | ✓ | ✓ | ✗ | ✗ |
| Prompt 模板增删改、版本回滚、渲染预览 | ✓ | ✓ | ✗ | ✗ |
| 工具参数声明、并行节点编排 | ✓ | ✓ | ✗ | ✗ |
| 租户管理（FR-033） | 仅平台租户的 admin | ✗ | ✗ | ✗ |

典型场景：

- **外部系统接入**：业务系统持 API Key 调对话接口。运维给该 Key 配白名单 `10.20.0.0/16` 与每分钟 120 次；超限时业务系统收到 429 与 `Retry-After`，按秒数退避；模型厂商故障时 5 次失败后立刻收到 503，而不是每次等 120 秒。
- **提示词复用**：开发者维护一份"客服话术"模板，含 `{{company}}`、`{{tone}}` 两个变量，三个智能体各自填变量绑定；模板改版后智能体列表提示"模板有新版本"，开发者逐个确认后重新保存（保存即生效；发布只是留一份版本快照）。
- **并行编排**：工作流同时调用两个 HTTP 接口取数，汇聚后交给智能体节点综合作答。

## 4. 功能需求

每条需求按固定结构写：现状 → 需求 → 契约（接口 / 数据 / 配置）→ 前端 → 边界与负向 → 验收 → 不做什么。

**400 与 422 的通用分界**（全文适用，与 `04-接口设计.md` 2.2 一致）：结构、类型、格式、范围、数量类校验由 pydantic schema 承担，失败返回 422（FastAPI 逐字段数组）；需要读库或需要跨字段语义判断的校验在服务层做，失败返回 400（可展示的字符串）。下文每处状态码都按此规则标注。

### 4.1 FR-025 入口限流

**现状**

- 仅两处 429：登录连续 5 次失败锁 10 分钟（`services/auth_service.py`，Redis 计数）；API Key 总量配额用尽（`services/api_key_service.authenticate`）。
- 没有任何速率维度的限制。一个 Key 只要配额没用完就可以在 1 秒内打满后端线程。

**需求**

三个维度独立计数，固定窗口（按自然分钟）：

| 维度 | 键 | 默认上限 / 分钟 | 可覆盖 |
|---|---|---|---|
| API Key | `rl:ak:{api_key_id}:{分钟}` | `RATE_LIMIT_API_KEY_PER_MINUTE=60` | 单个 Key 的 `rate_limit_per_minute`，0 表示用全局默认 |
| 登录用户（JWT） | `rl:user:{user_id}:{分钟}` | `RATE_LIMIT_USER_PER_MINUTE=300` | 否 |
| 匿名（仅 `POST /auth/login`） | `rl:ip:{ip}:{分钟}` | `RATE_LIMIT_IP_PER_MINUTE=20` | 否 |

- 算法选固定窗口而不是滑动窗口：与登录限流是同一套 `INCR + EXPIRE` 用法，实现与排障成本最低；边界处最多放过 2 倍瞬时流量，对本平台的调用规模可接受。
- 计数单位是"请求"，SSE 对话按一次请求计，不按 token。
- **被限流的请求不扣 API Key 配额**：`authenticate` 的顺序改为 Key 有效 → 归属账号可用 → IP 白名单（FR-026）→ 限流 → 扣配额。
- 超限响应：HTTP 429，`detail` 为"请求过于频繁，请 N 秒后重试"，响应头 `Retry-After: N`（到下一分钟的秒数）、`X-RateLimit-Limit`、`X-RateLimit-Remaining`（429 时为 0）。正常响应也带后两个头，便于调用方自适应。`BizError` 需支持携带响应头并由全局异常处理器透传，现有实现没有这个字段。
- `/health` 不计数。
- **降级**：Redis 不可用时放行，打 WARN，`/system/status` 新增 `rate_limit: {enabled, reason, api_key_per_minute, user_per_minute, ip_per_minute}`，`enabled=false` 进 `degraded`。与 `login_guard` 同款语义，且两者共用同一个 Redis 客户端与故障记录，不再各自维护一份。
- `RATE_LIMIT_ENABLED=false` 可整体关闭（配置性关闭，`enabled=false` 但 `reason` 写明"配置关闭"，不进 `degraded`）。

**契约**

- 数据：`api_keys.rate_limit_per_minute integer not null default 0`。
- 接口：`GET /api-keys` 与 `POST /api-keys` 的对象增加 `rate_limit_per_minute`；新增 `PUT /api-keys/{id}`（见 4.2 契约，两条需求共用）。
- 配置：`RATE_LIMIT_ENABLED`、`RATE_LIMIT_API_KEY_PER_MINUTE`、`RATE_LIMIT_USER_PER_MINUTE`、`RATE_LIMIT_IP_PER_MINUTE`。

**前端**

- API Key 页：列表新增"限速/分钟"列（0 显示为"默认 60"），新建与编辑表单新增该字段（整数，0～10000）。
- 请求层：收到 429 时提示文案带上 `Retry-After` 秒数；不自动重试。
- 工作台的降级提示沿用 `degraded` 数组，无需新增逻辑。

**边界与负向**

- 第 61 次请求 429 且 `used` 不增加；下一自然分钟恢复。
- 单 Key 覆盖值 120 时第 61～120 次通过；覆盖值为 0 时按全局。
- Redis 停掉：请求放行，`/system/status.rate_limit.enabled=false` 且 `degraded` 含 `rate_limit`；Redis 恢复后自动回到 `enabled=true`。
- 上限字段负数或超过 10000 → 422。

**验收**：AC-011。

**不做**：按 token 计费型限流、按接口路径的差异化上限、分布式滑动窗口。

### 4.2 FR-026 来源 IP 管控

**现状**

- 没有任何来源限制。`audit_logs.ip` 列存在但从未写入（`09` 第 4 节已知问题）。
- API Key 没有归属隔离：`services/api_key_service.list_api_keys` 返回全部 Key（docstring 却写"当前用户的"），`toggle_api_key / delete_api_key` 不校验归属，developer 今天就能停用和删除别人的 Key；前端 API Key 菜单只对 admin 渲染（`components/AppLayout.tsx`），developer 进不了页面。
- 部署上后端可能在 nginx 之后，`request.client.host` 会是代理地址。

**需求**

- **API Key 按创建人隔离（评审决策 ①）**：developer 的列表、编辑、启停、删除只作用于本人创建的 Key，操作他人的 Key 一律 404（不用 403，避免暴露存在性）；admin 作用于全部。前端 API Key 菜单对 developer 开放。这同时修掉现状里 toggle / delete 无归属校验的问题，与 `01` 第 3 节"developer 管理 API Key"的表述对齐。
- **API Key 级白名单**：`api_keys.allowed_ips` 为 CIDR 列表，空列表表示不限制。请求来源不在列表内 → 403 "API Key 不允许从该 IP 调用"，不扣配额，写审计 `api_key_ip_rejected`（detail 含 Key id 与来源 IP）。
- **全局黑名单**：配置 `IP_DENYLIST`（逗号分隔 CIDR），命中 → 403 "来源 IP 被拒绝"，所有路径生效（含 `/auth/login`，不含 `/health`）。拦截由独立的纯 ASGI 中间件完成，注册在 CORS 中间件内层，因此 403 响应同时带 CORS 头与 `trace_id`，浏览器端能读到可读的 403 而不是"网络错误"。
- **取客户端 IP 的唯一函数**：`core/request_context.get_client_ip()`。`TRUSTED_PROXY_ENABLED=true` 时先取 `X-Real-IP`，没有再取 `X-Forwarded-For` 第一个地址；否则取连接对端地址。默认 `false`：不信任任何转发头，避免无代理部署时被伪造头绕过白名单。nginx 反代必须用 `proxy_set_header` 覆写这两个头而不是追加，`08` 写明。
- 中间件把客户端 IP 与请求 ID 一样放进 contextvar，`core/audit.record_audit` 在调用方未传 `ip` 时自动填入，一次性解决 `audit_logs.ip` 空白问题，调用点不必逐个改。

**契约**

- 数据：`api_keys.allowed_ips jsonb not null default '[]'`。
- 接口：
  - `POST /api-keys` 请求体新增 `allowed_ips=[]`、`rate_limit_per_minute=0`。
  - 新增 `PUT /api-keys/{id}`，角色 AD，请求 `{name?, quota?, allowed_ips?, rate_limit_per_minute?}`，返回 Key 对象（不含明文）。
  - `GET /api-keys` 对 developer 只返回本人创建的 Key；`PUT`、`POST /{id}/toggle`、`DELETE /{id}` 对 developer 按 `user_id` 校验归属，不属于本人 → 404。admin 不受限。
  - 对象增加 `allowed_ips`。
- 配置：`IP_DENYLIST`（默认空）、`TRUSTED_PROXY_ENABLED`（默认 false）。
- 校验（schema 层 → 422）：每一项必须是合法 IPv4/IPv6 地址或 CIDR（用标准库 `ipaddress` 判定），错误信息指出第几项；列表长度上限 50。

**前端**

- API Key 页：新增"允许的 IP"列（显示条数，悬停看全部）与表单字段（每行一条）。
- 新增编辑入口（之前只有新建 / 启停 / 删除）；菜单对 developer 开放，developer 视角只看到本人创建的 Key。

**边界与负向**

- 白名单 `["10.0.0.0/8"]`，从 `127.0.0.1` 调用 → 403，`used` 不变，审计有记录。
- 白名单为空 → 任意来源通过。
- `TRUSTED_PROXY_ENABLED=false` 时带伪造 `X-Forwarded-For: 10.0.0.1` 仍按真实对端判定 → 403。
- `IP_DENYLIST` 含本机地址时登录接口 403、`/health` 仍 200。
- 非法 CIDR `"10.0.0.0/33"` → 422。
- developer 停用或删除他人创建的 Key → 404；admin 可以。
- 黑名单命中的 403 响应带 `Access-Control-Allow-Origin`（白名单内的 Origin）与 `trace_id`。

**验收**：AC-012。

**不做**：按用户（JWT）的 IP 白名单、地理位置封禁、动态封禁。

### 4.3 FR-027 模型调用熔断

**现状**

- `model_gateway/gateway.build_llm` 统一构建 `ChatOpenAI`，超时 `MODEL_HTTP_TIMEOUT=120` 秒，**未设置 `max_retries`**，落到 OpenAI SDK 默认的 2 次重试：超时类故障下一次"失败"实际是 3 次尝试，最长 3 × 120 秒。调用点三处：`services/chat_service.py`（对话、历史摘要、查询改写共用一个实例）、`workflow/engine.py` 智能体节点、`services/model_service.py` 连通测试。
- 上游厂商超时类故障时，每个请求最长要等 3 × 120 秒才失败，50 个并发对话会占满线程 6 分钟。

**需求**

- 以 `model_id` 为粒度的熔断器，状态 closed / open / half-open：
  - 连续失败达到 `MODEL_BREAKER_FAIL_THRESHOLD=5` 次 → open，持续 `MODEL_BREAKER_OPEN_SECONDS=30` 秒。
  - open 期间调用直接失败：`BizError(503, "模型「{name}」暂时不可用（熔断中，{n} 秒后自动重试）")`，不发起上游请求。对话接口把它作为 `error` 事件推给客户端，运行记录状态 failed、错误文本同上。
  - 到期后进入 half-open，放行一个探测请求；成功 → closed 并清零；失败 → 重新 open。
  - 成功一次即清零连续失败计数。
- **哪些失败计数**：连接失败、超时、上游 429、上游 5xx。**不计数**：400 / 401 / 403 / 404 这类配置或参数错误，它们不会因为等待而恢复，熔断反而会掩盖真正原因。
- 流式调用：拿到第一个 chunk 视为成功；建立流之前抛异常视为失败；流中途断开不计数（已经消耗了资源，且原因通常在客户端）。
- **SDK 重试归零（评审决策 ③）**：`build_llm` 显式传 `max_retries=settings.MODEL_MAX_RETRIES`（默认 0），故障处理统一交给熔断器，SDK 层不再自行重试。`MODEL_HTTP_TIMEOUT` 保持 120 秒（流式长回复需要）；熔断只缩短"故障之后"的等待，缩短不了首次故障那一次。连接超时与读超时分开配置作为后续可选项，不在本批。
- 历史摘要与查询改写（`chat_service` 两处 `except Exception` 降级）在熔断打开期间直接走既有降级路径（字符截断 / 原查询），不对外报 503；这两处的调用失败同样计入连续失败，计数来源不只主对话流。
- 半开态只放行一个探测请求：对话路由是 async 与线程混跑，放行判定必须在锁内原子完成，并发到达的第二个请求仍 503。
- 连通测试 `POST /models/{id}/test` 成功即关闭该模型的熔断，作为人工恢复手段。
- 状态存进程内存。多实例部署时各实例独立熔断，这是已知限制（与调度器多实例问题同类，`09` 第 4 节已记录），本批不上 Redis。

**契约**

- 接口：`GET /system/status` 新增 `model_breakers: [{model_id, name, state, consecutive_failures, opened_at, retry_after_seconds}]`，只列出非 closed 的模型；每个 open 的模型进 `degraded`，`item="model_breaker"`，`message` 含模型名。
- 配置：`MODEL_MAX_RETRIES`（默认 0）、`MODEL_BREAKER_FAIL_THRESHOLD`、`MODEL_BREAKER_OPEN_SECONDS`；阈值为 0 表示关闭熔断。

**前端**

- 模型页：从 `/system/status` 取 `model_breakers`，对应行显示"熔断中，N 秒后重试"标签；"测试连通"成功后刷新状态。
- 对话页：503 错误事件按现有 `error` 事件展示，无新增逻辑。

**边界与负向**

- 上游连接失败时 SDK 不重试：mock 的上游调用次数为 1，单次失败耗时不超过 1 个 `MODEL_HTTP_TIMEOUT`。
- 用不可达的 `api_base` 连续调用 5 次后，第 6 次在 100 毫秒内返回 503 且无上游请求（用 mock 计数断言）。
- 半开时并发 2 个请求只放行 1 个，另一个 503。
- 查询改写连续超时 5 次同样打开熔断。
- 30 秒后第一个请求放行；若成功则后续全部放行。
- 连续 4 次失败 + 1 次成功 → 计数清零，不熔断。
- 上游返回 401 十次 → 不熔断，每次都正常返回鉴权错误。
- 阈值配 0 → 永不熔断。

**验收**：AC-013。

**不做**：跨实例共享熔断状态、按错误率（而非连续次数）判定、自动切换备用模型。

### 4.4 FR-028 Prompt 模板管理

**现状**

- 提示词只存在于 `agents.system_prompt`（整段文本）与工作流智能体节点的 `config.prompt` 覆盖里。没有复用、没有变量、没有版本；改一句话要逐个智能体改。
- 智能体已有"发布即快照"与回滚（`agent_versions`），模板的版本机制照此设计，不另起一套。

**需求**

**4.4.1 模板实体**

- 字段：名称（唯一）、描述、内容、变量声明、版本号、创建人、创建 / 更新时间。
- 变量声明是数组，每项 `{name, description, required, default}`；`name` 匹配 `^[A-Za-z_][A-Za-z0-9_]*$`，同一模板内唯一，最多 30 个。
- 内容里用 `{{name}}` 引用变量。**保存时校验**：内容引用了未声明的变量 → 400 "模板引用了未声明的变量：x, y"；声明了但内容未使用 → 允许保存，响应里 `unused_variables` 列出，前端提示。
- 渲染是纯字符串替换，不引入 Jinja 之类的模板引擎：避免表达式能力带来的注入面，也让"模板里写了什么就渲染什么"可预期。P1 不支持转义字面量 `{{`。

**4.4.2 版本**

- 每次 `PUT` 若 `content` 或 `variables` 发生变化，`version + 1` 并写一条 `prompt_template_versions` 快照；只改名称 / 描述不升版本。
- 回滚到任一历史版本：内容与变量恢复到该快照，`version + 1`（与智能体回滚语义一致，历史不可篡改）。
- 删除模板：仍被智能体绑定 → 409 "仍有 N 个智能体绑定该模板"。

**4.4.3 智能体绑定**

- `agents` 新增 `prompt_template_id`（可空，FK SET NULL）、`prompt_template_version`（可空整数）、`prompt_variables`（JSONB，默认 `{}`）。
- `POST / PUT /agents` 传了 `prompt_template_id` 时：`system_prompt` 必须省略或为空，否则 400 "绑定模板时不能同时手填 system_prompt"；服务端用模板当前版本 + `prompt_variables` 渲染，写入 `system_prompt`，记录 `prompt_template_version`。必填变量缺失 → 400 "缺少必填变量：x"。
- 未传 `prompt_template_id`：行为与现在完全一样，三个新字段为空。
- **模板改版不自动传播**：智能体的 `system_prompt` 保持最近一次保存时渲染的结果。列表与详情返回 `prompt_template_outdated: true/false`（模板当前版本 > 绑定时版本），由开发者决定何时重新保存。列表页计算该标记必须一次批量查模板版本，禁止逐行查。
- **重新保存（PUT）即生效**：`system_prompt` 随保存立即更新，对话随之生效，与现有智能体编辑行为一致（对话读的是 `agents` 行而不是版本快照）；发布只影响版本快照。
- 发布快照（`agent_versions.snapshot`）包含三个新字段；回滚智能体时一并恢复。
- **对话运行时不变**：`chat_service` 仍只读 `agent.system_prompt`。

**4.4.4 渲染预览**

- `POST /prompt-templates/{id}/render`，请求 `{variables}`，返回 `{content, missing, unused}`；`missing` 非空时 400（把缺失名放在 detail 里）。不调模型，P1 不做"在线调试跑模型"。

**契约**

新表 `prompt_templates`：

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | bigint | PK | |
| name | varchar(128) | 非空，唯一 | |
| description | text | 可空 | |
| content | text | 非空 | 含 `{{var}}` |
| variables | jsonb | 非空，默认 `[]` | `[{name, description, required, default}]` |
| version | integer | 非空，默认 1 | |
| created_by | bigint | FK users RESTRICT，可空 | |
| created_at / updated_at | timestamptz | | |

新表 `prompt_template_versions`：

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | bigint | PK | |
| template_id | bigint | FK prompt_templates CASCADE，非空，索引 | |
| version | integer | 非空 | 与 template_id 联合唯一 |
| content | text | 非空 | |
| variables | jsonb | 非空 | |
| created_by | bigint | FK users SET NULL，可空 | |
| created_at | timestamptz | | |

`agents` 新增列：`prompt_template_id bigint null FK prompt_templates SET NULL`、`prompt_template_version integer null`、`prompt_variables jsonb not null default '{}'`。

接口 `/prompt-templates`（角色 AD，不接受 API Key）：

| 方法 路径 | 请求 | 响应 |
|---|---|---|
| GET /prompt-templates | 分页参数；`q` 名称模糊 | 分页信封，items `[{id, name, description, variables, version, created_by, updated_at}]`（不含 content，列表不下发大字段） |
| POST /prompt-templates | `{name, description="", content, variables=[]}` | 模板对象（含 content）+ `unused_variables`；409 重名；400 未声明变量 |
| GET /prompt-templates/{id} | | 模板对象 |
| PUT /prompt-templates/{id} | 同 POST，整体覆盖 | 模板对象；content / variables 变化时 version+1 |
| DELETE /prompt-templates/{id} | | `{code:0}`；409 被智能体绑定 |
| GET /prompt-templates/{id}/versions | 分页参数 | 分页信封，items `[{id, version, content, variables, created_at}]` 版本倒序 |
| POST /prompt-templates/{id}/rollback/{version_id} | | 模板对象，version+1；404 版本不属于该模板 |
| POST /prompt-templates/{id}/render | `{variables={}}` | `{content, missing: [], unused: []}`；400 缺必填 |

`/agents` 变更：请求体新增 `prompt_template_id?`、`prompt_variables?`；对象新增 `prompt_template_id`、`prompt_template_version`、`prompt_variables`、`prompt_template_outdated`。

审计：`prompt_template_create`、`prompt_template_delete`、`prompt_template_rollback`。

**前端**

- 新页面 `/prompt-templates`，菜单"提示词模板"，admin 与 developer 可见：列表（名称、变量数、版本、更新时间）、编辑抽屉（内容文本域 + 变量表格：名称 / 描述 / 必填 / 默认值）、版本历史（查看、回滚）、渲染预览（填变量看结果）。
- 智能体表单：新增"从模板生成"开关；开启后选模板、按声明填变量、只读展示渲染结果，`system_prompt` 输入框禁用；关闭后恢复手填。列表行显示"模板有新版本"标签。

**边界与负向**

- 内容引用 `{{tone}}` 但未声明 → 400。
- 必填变量缺失创建智能体 → 400 且不落库。
- 同时传 `system_prompt` 与 `prompt_template_id` → 400。
- 删除被绑定的模板 → 409；解绑后可删。
- 回滚到另一模板的版本 id → 404。
- 模板升版后，智能体列表该行 `prompt_template_outdated=true`；重新保存后变 false 且 `prompt_template_version` 跟到最新。
- 智能体回滚到绑定模板前的版本 → 三个字段恢复为空。
- caller 访问任一模板接口 → 403；API Key 访问 → 403。
- 变量超过 30 个 → 422。

**验收**：AC-014。

**不做**：模板在线跑模型调试、模板级权限、工作流智能体节点的 `config.prompt` 绑定模板（节点仍是手填覆盖）。

### 4.5 FR-029 工作流并行节点

**现状**

- `workflow/engine.py` 的 `NODE_BUILDERS` 有 10 类节点；边只有直连、条件（`when=true/false`）与循环（`when=loop/exit`）三种。
- `WorkflowState` 是不带 reducer 的 `TypedDict`，`steps` 与 `node_outputs` 由各节点整体覆盖写回。LangGraph 在同一超步里有两个节点写同一个无 reducer 的键时会抛 `InvalidUpdateError`，所以现有引擎天然不能并行。
- 图在保存时不做任何校验（`workflow_service.create_workflow / update_workflow` 直接落库）。

**需求**

**4.5.1 图契约**

- 新增两类节点：`parallel`（扇出）与 `join`（汇聚）。
- `parallel` 出边 ≥ 2 条，不带 `when`；每条出边开始一条**分支**。分支是线性链，只允许 `agent / tool / kb_retrieval / code / http` 五类节点，链尾必须连到同一个 `join`。
- `join` 入边 ≥ 2 条，且全部来自同一个 `parallel` 的分支。P1 只支持一种汇聚模式：输出为字典 `{分支末节点 id: 该节点输出}`；通用的 `output_field` 仍可用于从中提取字段。
- `parallel` 节点自身把输入原样作为输出传给各分支（透传），config 为空对象。

**4.5.2 分支内的输入解析**

- 分支内节点的默认输入不能再是 `state.output`（同一超步多个分支同时写，取值不确定）。规则：分支首节点默认取 `parallel` 节点的输出；后续节点默认取本分支上一节点的输出（编译期按边算出前驱，`node_outputs[前驱 id]`）。
- 分支内 `input_ref` 允许 `{{input}}`、`{{node_id}}`、`{{node_id.path}}`；**不允许 `{{output}}`**，校验期拒绝。

**4.5.3 校验**

- 新增 `workflow/validation.validate_graph(graph) -> list[str]`，保存（`POST / PUT /workflows`）、编辑器测试运行、正式运行前都调用；有错误 → 400，detail 为逐条错误文本用分号连接。前驱映射由独立的纯函数 `branch_predecessors(graph)` 计算，校验函数不承担第二职责。
- 校验必须在服务层显式调用，不能只靠 `build_workflow` 内部抛错：现有 `test_run_workflow / execute_workflow` 会吞掉执行期异常并返回 failed，抛在里面的 400 到不了调用方，还会白建一条 failed 运行记录。正式运行在创建运行记录之前校验，非法图返回 400 且不产生运行记录；编辑器测试运行在执行前校验返回 400；定时任务触发遇到非法图没有调用方可接收 400，按 failed 落库。
- 校验规则（仅针对并行，不改变既有图的可保存性）：
  1. `parallel` 出边少于 2 → "并行节点 {id} 至少需要 2 条分支"。
  2. 分支内出现 `condition / loop / human_review / parallel / join(非本组)` → "并行分支内不支持 {type} 节点（{id}）"。
  3. 分支未汇聚到同一 `join` → "并行节点 {id} 的分支必须汇聚到同一个汇聚节点"。
  4. `join` 入边来自不同 `parallel` 或不足 2 条 → "汇聚节点 {id} 的入边必须全部来自同一个并行节点且不少于 2 条"。
  5. 分支内节点 `input_ref` 为 `{{output}}` → "并行分支内的节点 {id} 不能引用 {{output}}"。
  6. 并行嵌套并行 → 规则 2 覆盖。

**4.5.4 引擎改造（前置）**

- `WorkflowState` 改为带 reducer：`steps` 用列表追加，`node_outputs` 用字典合并，`output` 用"取最后一次写入"。节点改为只返回增量（`steps: ["code"]`、`node_outputs: {id: out}`）。这是纯重构，对既有 10 类节点的行为无变化，必须先单独提交并跑全量回归后再加并行节点。现有工作流测试只有一条 start→end 用例，构不成回归基线，重构前要先补特征化测试（计划 2.4a）。
- 同一超步内并行分支的完成顺序不确定：`steps` 里两条分支的条目顺序不保证，只保证集合完整，展示与断言都按集合处理；并行超步结束时 `output` 是哪个分支的输出同样不确定，因此 `join` 节点执行后把 `output` 覆盖为汇聚字典，`join` 之后的节点默认输入即该字典。
- 并行分支在 LangGraph 同一超步内由执行器并发跑；节点函数里的 `asyncio.run` 与 `SessionLocal` 在工作线程中各自独立，无需改。
- 任一分支失败 → 整条运行 failed，节点日志按现有 `_node_failed` 写；同超步其他分支可能已完成，其节点日志保留 success。

**契约**

- `workflows.graph` 的 `nodes[].type` 新增 `parallel`、`join`；`parallel` 出边无 `when`。
- `POST / PUT /workflows`、`POST /workflows/test-run`、`POST /workflows/{id}/run` 新增 400 "图校验失败：..."。
- `run_nodes.node_type` 新增取值 `parallel`、`join`。

**前端**

- 节点面板新增"并行"与"汇聚"；`buildDetail` 摘要显示分支数 / 入边数；连线时从 `parallel` 拉出的边不弹 `when` 选择。
- 保存 / 测试运行的 400 直接展示 detail。
- `WorkflowEditor.tsx` 现已 358 行，超过 `07-前端规范.md` 的 300 行阈值；本需求触碰该文件，按"触发即拆"原则把节点面板常量与节点配置表单拆成独立模块，父组件只做编排。

**边界与负向**

- 两条分支各是一个 `code` 节点 `time.sleep(1)`，运行总耗时 < 1.6 秒（证明并发），`join` 输出的键集合等于两个分支末节点 id；`steps` 按集合比较。
- 用非法图调用正式运行 → 400 且 `runs` 表不新增记录；编辑器测试运行同样 400。
- 只有 1 条分支 → 保存 400。
- 分支内放 `loop` → 400。
- 两条分支汇到不同 `join` → 400。
- 分支内 `input_ref={{output}}` → 400。
- 一条分支 `http` 节点目标不可达 → 运行 failed，该节点日志 failed，另一分支节点日志 success。
- 既有不含并行节点的图（含条件与循环）保存与运行行为不变（回归）。

**验收**：AC-015。

**不做**：并行嵌套、分支内条件 / 循环 / 人工审核、汇聚模式 `list / first`、分支级超时。

### 4.6 FR-030 工具参数 schema

**现状**

- `tools/langchain_tools._build_http_tool` 把 HTTP 工具暴露为只有一个字符串参数 `arguments` 的 `StructuredTool`，由模型自己拼 JSON 字符串，再 `json.loads`；拼错时按空参数调用并打 WARN。
- 模型看不到参数名与类型，只能靠 `description` 猜；`POST /tools/{id}/test` 的 `args` 不做任何校验。

**需求**

- `tools.config.parameters` 声明参数，取 JSON Schema 子集：

  ```json
  {"type": "object",
   "properties": {"city": {"type": "string", "description": "城市名", "enum": ["北京", "上海"]},
                  "days": {"type": "integer", "description": "预报天数"}},
   "required": ["city"]}
  ```

  - `type` 只允许 `string / number / integer / boolean`；不支持嵌套对象与数组（P1）。
  - `required` 必须是 `properties` 的子集；属性名匹配 `^[A-Za-z_][A-Za-z0-9_]*$`；最多 20 个。
  - 以上全部在 schema 层校验，违反 → 422 并指出字段。
- `_build_http_tool` 按 schema 用 `pydantic.create_model` 生成 `args_schema`，函数签名变为关键字参数，直接把参数字典交给 `_execute_http`（GET 走 query，其余走 JSON body，与现在一致）。
- 未声明 `parameters` 或 `properties` 为空的工具按**无参数工具**暴露，模型只能以 `{}` 调用。
- 模型传参不符合 schema 时，LangChain 的校验错误作为工具结果文本返回给模型让其纠正（不抛异常中断对话），同时打 WARN。
- `POST /tools/{id}/test` 先按 schema 校验 `args`，不符合 → 400 "参数校验失败：..."，不发起调用。
- 工作流 `tool` 节点的固定 `config.args` 在运行时按 schema 校验，不符合 → 节点 failed，错误文本同上。
- 存量 HTTP 工具：**行为变化点是后端上线那一刻**，未声明参数的工具从此按无参数工具暴露，不保留"字符串参数"的旧行为。一次性迁移脚本只把这个隐式状态显式化（回填 `parameters = {"type":"object","properties":{},"required":[]}`）并打印清单，不改变运行时行为，漏跑只影响"未声明参数"标签。上线前先用一条 SQL 查出 `config` 里没有 `parameters` 的 HTTP 工具清单发给使用方，**开发者需要逐个补声明**。

**契约**

- 数据：`tools.config` 新增键 `parameters`（结构如上），`03-数据库设计.md` 4.2 同批更新。
- 接口：`POST / PUT /tools` 的 `config.parameters` 校验；`POST /tools/{id}/test` 新增 400；`GET /tools` 对象不变（`config` 原样返回）。

**前端**

- 工具表单新增"参数"表格：名称、类型（下拉四选一）、必填、描述、枚举值（逗号分隔，仅 string）；保存时组装成 schema。表格抽成独立组件。
- 列表：`properties` 为空的 HTTP 工具显示"未声明参数"标签，提醒补声明。
- 测试调用弹窗按声明生成输入项，不再手写 JSON。

**边界与负向**

- `type: "array"` → 422。
- `required: ["x"]` 但 `properties` 无 `x` → 422。
- 测试调用缺必填 → 400 且无外部请求。
- 模型传 `days: "三"`（integer 字段给字符串）→ 工具返回校验错误文本，对话继续。
- 迁移脚本重复执行不重复回填（已有 `parameters` 的跳过）。

**验收**：AC-016。

**不做**：嵌套对象 / 数组参数、参数值模板（如从上下文注入）、内置工具改造（`current_time / calculator` 已是原生签名）。

### 4.7 FR-031 对话摘要持久化

**现状**

- `chat_service._build_history_messages`：消息超过 `CHAT_HISTORY_MAX_MESSAGES=20` 条时，把更早的全部消息交给 `_summarize_history` 调一次模型生成不超过 150 字的摘要；失败退回前 2000 字符截断。
- 摘要不落库，每一轮都重新生成，且输入随会话增长线性变大。`02-架构设计.md` 第 5 节已把它列为代价项。

**需求**

- `conversations` 新增 `summary`（text，可空）、`summary_upto_message_id`（bigint，可空）、`summary_updated_at`（timestamptz，可空）。
- 构建历史时：
  1. 消息总数 ≤ 20 → 与现在相同，全部原文。
  2. 否则把更早消息中 `id > summary_upto_message_id` 的记为**待折叠**。待折叠条数 ≥ `CHAT_SUMMARY_BATCH_MESSAGES=10` 时，调一次模型把"旧摘要 + 待折叠消息"压成新摘要，落库并推进 `summary_upto_message_id`；不足 10 条时不调模型，待折叠消息按原文注入。
  3. 注入顺序：`[摘要 SystemMessage] + 未折叠的更早消息原文 + 最近 20 条`。
- 效果：模型摘要调用从"每轮一次"降为"每 5 轮一次"，且每次输入有界（旧摘要 ≤ 150 字 + 最多 10 条消息）。
- 摘要失败：保留旧摘要与 `summary_upto_message_id` 不动，本轮待折叠消息按原文注入并截断到 2000 字符，打 WARN。不把截断文本当摘要落库。
- 同一会话并发两次请求可能各自触发一次摘要并互相覆盖 `summary_upto_message_id`：两次结果方向一致、内容无害，允许后写覆盖，不加锁。
- 当前没有删除单条消息的接口，摘要无需失效逻辑；若将来新增删除消息或"重新生成"删除旧回复的接口，必须同批处理 `summary_upto_message_id` 越界的情况（写进 `06-后端规范.md`）。

**契约**

- 数据：三列如上。
- 接口：`GET /conversations` 的 item 新增 `summary`（可空字符串，≤ 150 字）便于排查；会话接口对 API Key 开放，该字段对 API Key 调用方同样可见，仅用于排查。`GET /conversations/{id}/messages` 不变。
- 配置：`CHAT_SUMMARY_BATCH_MESSAGES=10`。

**前端**

- 无必做改动。对话页可选在会话信息里展示"已压缩 N 条更早消息"，不在本批范围。

**边界与负向**

- 会话 35 条消息（20 最近 + 15 更早）：第一次请求调 1 次摘要，`summary_upto` 指向第 15 条；再发 2 轮（39 条），更早 19 条中待折叠 4 条 < 10，不调摘要（用 mock 计数断言为 0）。
- 摘要模型抛异常：对话正常返回，`summary` 字段为空，日志有 WARN。
- 删除会话级联删除，无残留。

**验收**：AC-017。

**不做**：按 token 而非条数触发、摘要可编辑、跨会话长期记忆。

### 4.8 FR-032 Rerank 模型接入（中期）

**现状**

- `rag/rerank.rerank(query, candidates, keywords)` 是词法启发式：关键词覆盖率与混合分各占一半。`rag/retriever._prune` 的阈值（`min_score=0.01`、`gap_ratio=0.35`）按这套分数分布调过。
- `06-后端规范.md` 第 8 节已把 `rerank` 定义为可替换扩展点，接口固定。

**前置条件**

- 已配置真实向量模型（`EMBEDDING_API_KEY` 非空且 `/health` 报 `embedding_mode=model`）。当前决定暂不配向量模型，此时 RRF 候选以关键词召回为主，Rerank 只能在低质量候选里排序，收益不足以覆盖每次检索多一次外部调用的延迟。**未满足前置条件不启动本需求。**

**需求**

- 配置 `RERANK_PROVIDER`：空（关闭，默认）/ `cohere`（Cohere、Jina、TEI、vLLM、SiliconFlow 等共用的 `POST /rerank` 契约：`{model, query, documents, top_n}` → `results[{index, relevance_score}]`）/ `dashscope`（阿里云百炼 `text-rerank` 契约）。另配 `RERANK_API_BASE`、`RERANK_API_KEY`、`RERANK_MODEL`、`RERANK_TIMEOUT=5`、`RERANK_CANDIDATES=20`、`RERANK_MIN_SCORE=0.2`、`RERANK_GAP_RATIO=0.35`。
- 流程：RRF 融合 → 取前 `RERANK_CANDIDATES` 条 → 模型重排，`score` 直接取 `relevance_score` → 用 Rerank 专用阈值 `_prune` → 逐条鉴权（不变）。
- **降级**：模型调用失败或超时 → 退回词法重排，打 WARN；`rag/rerank.rerank_status()` 汇报 `{configured, mode: model|lexical, provider, model, last_error}`，接进 `/system/status` 与 `degraded`。未配置属配置性（`configured=false`，不进 `degraded`），配置了但失败属故障性（`last_error` 非空，进 `degraded`），与 embedding 的两类降级口径一致。
- 检索结果 `meta` 之外新增 `rerank_mode`；评测接口的 enriched 输出新增 `rerank_score`；审计 `rag_retrieve` 的 detail 新增 `rerank_mode`。

**契约**

- 接口：`POST /knowledge-bases/{id}/search` 响应 item 新增 `rerank_mode`、`rerank_score`（未配置时 `rerank_mode=lexical`、`rerank_score` 为空）；`/system/status` 新增 `rerank` 块。
- 配置：如上 8 项。

**前端**

- 知识库检索评测页：显示 `rerank_mode` 与 `rerank_score` 列；顶部降级告警复用 `degraded`。

**边界与负向**

- 配置 `cohere` 且服务正常：结果按 `relevance_score` 降序，`rerank_mode=model`。
- 服务超时（mock 延迟 6 秒）：请求仍在词法重排下返回，`rerank_mode=lexical`，`/system/status.degraded` 含 `rerank`。
- 未配置：`rerank_mode=lexical`，`degraded` 不含 `rerank`。
- 候选为空：不调 Rerank 服务。

**验收**：AC-018。

**不做**：本地跑 Rerank 模型、按知识库配置不同 Rerank 模型、Rerank 结果缓存。

### 4.9 FR-033 轻量多租户骨架（中期，有触发条件）

**现状**

- 17 张表无任何租户 / 组织字段。行级隔离只有两处：会话按 `user_id`，知识库按 `is_public / visible_roles`。其余资源角色内全员可见。
- `09-演进路线.md` 第 5 节把"完整多租户"列为不做；`10-差距分析.md` 4.2 认为租户列必须在建表期就定，主张先做轻量骨架。两者已在 2026-09-05 统一为：**完整多租户不做，轻量骨架按触发条件启动**。

**4.9.1 触发条件（满足任一才启动开发）**

1. 出现第二条真实业务线接入，且两条业务线的智能体 / 知识库 / API Key 需要互不可见。
2. 需要按业务线分别统计调用量或成本。
3. 管理层或合规要求业务线之间数据不可见。

未触发时本需求只完成设计评审（4.9.2～4.9.4 的决策点确认），不写代码。

**4.9.2 骨架设计**

- 新表 `tenants`：`id`、`code`（唯一短码）、`name`、`is_active`、`created_at`。安装时创建 `platform` 租户（id=1），**存量数据全部归入该租户**。
- `users.tenant_id` 非空 FK；用户只属于一个租户。
- 除推导表外的全部资源表新增 `tenant_id` 非空 FK 并建索引，当前为 10 张：`agents`、`tools`、`knowledge_bases`、`workflows`、`conversations`、`runs`、`api_keys`、`scheduled_jobs`、`audit_logs`、`prompt_templates`（本批新增，已计入；以后再加资源表必须带租户列）。`documents / document_chunks / messages / run_nodes / agent_versions / prompt_template_versions` 经父表推导，不加列。
- 唯一约束范围：`tenants.code` 全局唯一；`users.username` 保持全局唯一（登录不带租户）；`prompt_templates.name` 由全局唯一改为 `(tenant_id, name)` 联合唯一。
- `models.tenant_id` **可空**：空表示平台共享模型，任何租户可读可用、只有平台租户的 admin 可增删改；非空表示租户私有。
- **平台管理员** = `platform` 租户的 admin，额外能管理租户与共享模型；其他租户的 admin 只管本租户。角色枚举不变。
- 隔离规则：服务层所有按 id 取资源的查询都带 `tenant_id = 当前用户租户`，跨租户一律 404（不用 403，避免暴露存在性）。列表查询同理。租户信息每次请求从 `users` 行读取，不进 JWT，停用租户立即生效。
- API Key 继承归属用户的租户；检索 `_acl_condition` 与 `_authorize` 两道闸门同步加租户条件；审计写 `tenant_id`。

**4.9.3 契约**

- 新增 `/tenants`（仅平台管理员）：`GET`（分页）、`POST {code, name}`、`PUT /{id} {name?, is_active?}`；不提供删除，只能停用。
- `POST /users` 新增 `tenant_id`：平台管理员可指定，租户管理员只能建本租户用户（传了别的租户 → 404）。
- `GET /auth/me` 新增 `tenant: {id, code, name}`。
- 所有资源对象新增 `tenant_id`。

**4.9.4 迁移**

- 前置：先完成 `09` 第三梯队的 Alembic（计划 3.2a），10 张表加列与改约束用 Alembic 版本管理，不再手写脚本。
- 迁移顺序：建 `tenants` → 插入 `platform` → 各表加可空列并回填 1 → 改为非空 → 建索引 → `prompt_templates` 唯一约束改为 `(tenant_id, name)`。幂等：每步先查再做。

**前端**

- 顶栏显示当前租户名；平台管理员多一个"租户管理"页；用户管理表单在平台管理员视角多一个租户下拉。

**边界与负向**（每类资源至少一条跨租户用例）

- 租户 B 的 developer 用租户 A 的智能体 id 调 `GET /agents/{id}` → 404；对话 → 404；工作流运行 → 404；知识库检索 → 结果为空且审计记录鉴权剔除。
- 租户 B 的 admin 创建用户时传 `tenant_id=A` → 404。
- 共享模型对所有租户可见；租户私有模型对其他租户 404。
- 停用租户后该租户用户登录 → 403 "租户已停用"。
- 迁移脚本在已迁移的库上重复执行不报错、不重复插入。

**验收**：AC-019。

**不做**：租户级配额与计量、企业 SSO、细粒度资源授权（RBAC 细化到单个资源）、租户间共享知识库、租户删除。

## 5. 非功能需求（新增与修订）

| 编号 | 类别 | 要求 | 说明 |
|---|---|---|---|
| NFR-002 | 安全 | 修订：CORS 改为白名单 `CORS_ORIGINS`（逗号分隔，默认只放行本机前端地址） | 随 FR-025 / FR-026 的入口治理一并处理，`09` 第三梯队的"CORS 白名单"由此关闭 |
| NFR-008 | 可用性 | 入口治理（限流、IP 名单）任何依赖故障都不能让平台不可用：Redis 故障放行并报降级；配置解析失败启动时报错退出而不是静默关闭 | 与登录限流同款"降级可见"语义 |
| NFR-009 | 一致性 | 熔断状态与限流计数在多实例部署下不共享；文档写明，单实例部署是当前支持形态 | 与调度器多实例问题同级，`08-运行与部署.md` 注明 |
| NFR-010 | 性能 | 智能体列表的 `prompt_template_outdated`、工具列表的"未声明参数"都必须一次批量计算，不得逐行查询 | 延续 `06-后端规范.md` 第 4 节禁 N+1 |
| NFR-011 | 可回退 | 每条需求的数据变更都有幂等迁移脚本；FR-030 的一次性回填脚本打印受影响清单 | 延续 `03-数据库设计.md` 第 7 节 |

## 6. 验收标准

| 编号 | 对应 | 标准 |
|---|---|---|
| AC-011 | FR-025 | 同一 API Key 一分钟内第 61 次请求返回 429 且带 `Retry-After`，`used` 不增加；停掉 Redis 后请求放行且 `/system/status.degraded` 含 `rate_limit` |
| AC-012 | FR-026 | 白名单外来源调用返回 403、配额不变、审计有 `api_key_ip_rejected` 且 `ip` 列非空；`IP_DENYLIST` 命中时登录接口 403 而 `/health` 正常 |
| AC-013 | FR-027 | 上游失败时 SDK 不重试，单次失败耗时不超过 1 个 `MODEL_HTTP_TIMEOUT`；不可达模型连续 5 次失败后第 6 次在 100 毫秒内返回 503 且无上游请求；半开时并发 2 个只放行 1 个；30 秒后放行探测；连通测试成功后恢复；上游 401 不触发熔断 |
| AC-014 | FR-028 | 创建含变量模板并绑定到智能体，缺必填变量 400；模板升版后智能体列表标记过期，重新保存后消失；删除被绑定模板 409；模板升版本身不改变对话使用的 `system_prompt`，重新保存后对话立即使用新渲染结果 |
| AC-015 | FR-029 | 两条 `sleep(1)` 分支的工作流总耗时低于 1.6 秒且汇聚输出的键集合等于两个分支末节点 id；五条校验负向用例保存均 400，运行非法图 400 且无运行记录；既有条件 / 循环 / 人工审核工作流回归通过 |
| AC-016 | FR-030 | 声明 `city` 必填后测试调用缺 `city` 返回 400；模型以结构化参数调用工具成功；迁移后存量工具在列表标记"未声明参数" |
| AC-017 | FR-031 | 35 条消息的会话首轮调 1 次摘要并落库；随后 2 轮摘要调用 0 次；摘要失败时对话正常且日志有 WARN |
| AC-018 | FR-032 | 配置 Rerank 服务后检索结果 `rerank_mode=model` 并按 `rerank_score` 降序；服务超时时退回 `lexical` 且 `degraded` 含 `rerank` |
| AC-019 | FR-033 | 两个租户各建一套资源后，任一租户对另一租户的智能体 / 工作流 / 知识库 / API Key 的读、改、删、对话、检索全部 404 或空结果；迁移脚本在已迁移库上重复执行无副作用 |

## 7. 变更汇总

### 7.1 数据库

| 表 | 变更 | 需求 |
|---|---|---|
| `api_keys` | 新增 `allowed_ips jsonb default '[]'`、`rate_limit_per_minute integer default 0` | FR-025 / 026 |
| `conversations` | 新增 `summary text`、`summary_upto_message_id bigint`、`summary_updated_at timestamptz` | FR-031 |
| `prompt_templates`、`prompt_template_versions` | 新表 | FR-028 |
| `agents` | 新增 `prompt_template_id`、`prompt_template_version`、`prompt_variables` | FR-028 |
| `tools.config` | JSON 新增键 `parameters`；一次性回填 | FR-030 |
| `workflows.graph` | 节点类型新增 `parallel / join` | FR-029 |
| `tenants` 及 10 张表的 `tenant_id` | 新表与新列 | FR-033（触发后） |

### 7.2 接口

| 变更 | 需求 |
|---|---|
| 新增 `PUT /api-keys/{id}`；Key 对象新增两个字段；developer 的 list / PUT / toggle / delete 按归属过滤（他人 → 404）；新增 429（限流）、403（IP） | FR-025 / 026 |
| `/system/status` 新增 `rate_limit`、`model_breakers`、`rerank` 块与对应 `degraded` 项 | FR-025 / 027 / 032 |
| 新增 `/prompt-templates` 8 个接口；`/agents` 请求与响应新增模板字段 | FR-028 |
| `/workflows` 保存与运行新增 400 图校验失败 | FR-029 |
| `/tools` 保存校验 `parameters`；`/tools/{id}/test` 新增 400 | FR-030 |
| `GET /conversations` item 新增 `summary` | FR-031 |
| `/knowledge-bases/{id}/search` item 新增 `rerank_mode`、`rerank_score` | FR-032 |
| 新增 `/tenants`；`/users`、`/auth/me` 新增租户字段 | FR-033（触发后） |

### 7.3 配置项

| 配置 | 默认 | 需求 |
|---|---|---|
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_API_KEY_PER_MINUTE` / `RATE_LIMIT_USER_PER_MINUTE` / `RATE_LIMIT_IP_PER_MINUTE` | true / 60 / 300 / 20 | FR-025 |
| `IP_DENYLIST` / `TRUSTED_PROXY_ENABLED` / `CORS_ORIGINS` | 空 / false / `http://localhost:18056` | FR-026 / NFR-002 |
| `MODEL_MAX_RETRIES` / `MODEL_BREAKER_FAIL_THRESHOLD` / `MODEL_BREAKER_OPEN_SECONDS` | 0 / 5 / 30 | FR-027 |
| `CHAT_SUMMARY_BATCH_MESSAGES` | 10 | FR-031 |
| `RERANK_PROVIDER` / `RERANK_API_BASE` / `RERANK_API_KEY` / `RERANK_MODEL` / `RERANK_TIMEOUT` / `RERANK_CANDIDATES` / `RERANK_MIN_SCORE` / `RERANK_GAP_RATIO` | 空 / 空 / 空 / 空 / 5 / 20 / 0.2 / 0.35 | FR-032 |

## 8. 风险与开放问题

| 风险 / 问题 | 影响 | 应对 |
|---|---|---|
| 引擎状态改 reducer 后既有节点行为漂移 | 所有工作流 | 先单独提交纯重构并跑全量回归（`tests/test_workflows.py` + 编辑器测试运行），再加并行节点 |
| 存量 HTTP 工具在 FR-030 后端上线时变为无参数工具（迁移脚本不改行为） | 依赖这些工具的智能体行为变化 | 上线前 SQL 查清单发使用方；迁移脚本再次打印；工具列表标记；发布说明写明"需补参数声明" |
| SDK 重试归零后单次网络抖动直接失败 | 偶发一次对话报错 | 熔断只计连续失败，不会因单次抖动打开；对话页已有"重新生成"入口；`MODEL_MAX_RETRIES` 可按环境调整 |
| `TRUSTED_PROXY_ENABLED` 配错 | 白名单失效或全部拒绝 | 默认 false；`08-运行与部署.md` 写明 nginx 场景必须开且 nginx 需覆写 `X-Forwarded-For` |
| 熔断误伤（上游短暂抖动） | 30 秒内该模型不可用 | 阈值可配；连通测试可手动恢复；只计连续失败 |
| Prompt 模板"不自动传播"被误解为"改了没生效" | 用户困惑 | 列表明显标记过期；模板编辑页保存后提示"N 个智能体需要重新保存" |
| Rerank 在未配向量模型时收益不明 | 白花延迟 | 前置条件写死，未满足不启动 |
| 多租户触发后工作量大（17 表、全部服务层查询） | 周期长 | 只在触发条件满足后做；先评审 4.9.2 决策点；按资源逐个提交，每个资源带跨租户负向用例 |
| 已关闭：developer 能否看到 / 操作他人的 API Key | 曾影响 list / PUT / toggle / delete 四个接口的行级判断与前端菜单 | 2026-09-05 评审决策 ①：按创建人隔离，见 4.2 |
| 已关闭：`CORS_ORIGINS` 默认值 | 影响现有部署 | 2026-09-05 评审决策 ⑤：维持 `http://localhost:18056`；当前服务器是同源反代不受影响，`docker-compose.yml` 与 `.env.example` 给示例 |

## 9. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| V0.1 | 2026-09-05 | 初版：FR-025～FR-033、NFR-008～011、AC-011～019 |
| V0.2 | 2026-09-05 | 按 `13-差距补齐评审报告.md` 修订：400 / 422 通用分界；API Key 按创建人隔离；SDK 重试归零与摘要 / 改写计入熔断、半开并发；PUT 即生效；并行 `steps` 顺序与 `join` 覆盖 `output`、运行前显式校验；工具行为变化点改为后端上线；摘要并发覆盖允许；多租户唯一约束范围与 Alembic 前置；FR-028 降为 P1；关闭两个开放问题 |
