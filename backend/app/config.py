import ipaddress
import os
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    """逗号分隔的环境变量 → 去空白、去空项的列表。"""
    return [v.strip() for v in (value or "").split(",") if v.strip()]


class Settings(BaseSettings):
    # 默认读 .env；同一份代码同时维护多套环境（云端 / 本机）时，用 ENV_FILE=.env.local 切到另一份，
    # 两份都留在机器上、互不覆盖。两者都在 .gitignore 里。
    model_config = SettingsConfigDict(env_file=os.environ.get("ENV_FILE", ".env"), extra="ignore")

    APP_NAME: str = "Agent Platform"
    API_V1_PREFIX: str = "/api/v1"
    # 生产关闭交互式文档（docs/09 第三梯队）。/docs、/redoc、/openapi.json 会把全部路由、请求体结构
    # 与鉴权方式公开出去，对一个可被外部系统调用的中台等于免费给出攻击面清单。
    # 默认 False（开发时看文档方便），部署时在 .env 设 API_DOCS_ENABLED=true 才打开。
    API_DOCS_ENABLED: bool = False
    # 空库首次启动时 admin 的口令（只在库里没有 admin 时用）。不配置则用内置默认口令并要求首次登录改密；口令不进日志
    INITIAL_ADMIN_PASSWORD: str = ""
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    AES_KEY: str = "change-me-32-bytes-key"
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/agent_platform"
    REDIS_URL: str = "redis://localhost:6379/0"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "kb-docs"
    # MinIO 单次读写超时秒数（连接超时固定 5 秒）：几十 MB 的文件走公网要留足，但不能无限等
    MINIO_TIMEOUT: int = 120
    MODEL_HTTP_TIMEOUT: int = 120
    # 模型调用熔断（FR-027）。SDK 重试归零：故障处理统一交给熔断器；阈值 0 表示关闭熔断
    MODEL_MAX_RETRIES: int = 0
    MODEL_BREAKER_FAIL_THRESHOLD: int = 5
    MODEL_BREAKER_OPEN_SECONDS: int = 30
    # 模型调用全量日志（2026-11-08）：每次请求的地址、请求体、响应体、工具定义都存进 llm_calls。
    # 单条报文按字符数截断到这么多（默认 256KB）；0 表示不记录。凭据一律打码，其余全部保留
    LLM_LOG_ENABLED: bool = True
    LLM_LOG_MAX_CHARS: int = 262144
    # 数据保留：llm_calls 与 audit_logs 只增不减，需要定期清超期行（retention_service，每日一次）。
    # 单条调用日志可达 256KB×2，真实使用下几个月就到 GB 级；审计日志每次写操作一条。
    # 关掉 DATA_RETENTION_ENABLED 则任务直接跳过（给需要长期留存的部署一个开关）。
    DATA_RETENTION_ENABLED: bool = True
    # 调用日志是排查依据，留久一点；审计日志要满足合规追溯，也更久
    LLM_LOG_RETENTION_DAYS: int = 30
    AUDIT_LOG_RETENTION_DAYS: int = 180
    # 卡住运行的处置阈值（docs/15 OP-10）：超过这么多分钟仍是 running 的运行视为"卡住"
    # （进程被杀后没收尾的幽灵记录），允许人工置为 failed 并回收检查点。
    # 不能取得太短：真实的长工作流会跑几十分钟，误判会让人把还在跑的运行当成卡住处置掉。
    STUCK_RUN_MINUTES: int = 60
    # 工作流检查点回收（docs/15 WF-12）：终态运行本该在收尾时删掉检查点，这里兜底清残留的
    # （进程被杀、清理失败），给一个宽限期避免与"刚收尾、正在删"的运行抢同一份数据。
    CHECKPOINT_TERMINAL_GRACE_HOURS: int = 24
    # awaiting_review 的检查点是 resume 找回中断点的唯一依据，不能按终态那样清；
    # 只清超过这么多天仍未审批的，同时把该运行收尾为 failed（否则审批一提交会从空 state 重跑）。
    CHECKPOINT_AWAITING_REVIEW_RETENTION_DAYS: int = 7
    RAG_TOP_K: int = 4
    CHAT_HISTORY_MAX_MESSAGES: int = 20
    # 对话摘要持久化（FR-031）：更早消息里未折叠进摘要的攒够这么多条才调一次模型，不足时按原文注入
    CHAT_SUMMARY_BATCH_MESSAGES: int = 10
    # RAG 查询改写：默认关闭。开启后每条消息多一次模型调用（DeepSeek 类模型实测 4～9 秒），只在召回质量明显不足时打开
    RAG_QUERY_REWRITE_ENABLED: bool = False
    RAG_QUERY_REWRITE_TIMEOUT_SECONDS: int = 3
    # 单个上传文件的大小上限（MB），超出 413。使用者真实导入过 40MB 级的 xlsx，留足余量；
    # 前面有 nginx 时 client_max_body_size 要设成同值（nginx 默认 1MB）
    KB_UPLOAD_MAX_MB: int = 200
    # 同时处理的文档数：向量模型与库都是共享资源，并发只会让每篇都变慢、进度与预计时间失真；排队的文档保持 uploading
    INGEST_CONCURRENCY: int = 1
    # 处理中的文档多久没有心跳视为中断：可以在页面"继续处理"；后端启动时自动续本机未完成的文档
    INGEST_STALL_SECONDS: int = 180
    INGEST_AUTO_RESUME: bool = True
    # 入库流水线的调优参数：这里是 .env 默认值，页面"导入设置"改的值存 system_settings 表并优先生效（对下一篇开始处理的文档）
    INGEST_BATCH_SIZE: int = 100  # 每批切片数：一批向量化完成后一次提交，chunk_count 按批推进
    INGEST_EMBED_CONCURRENCY: int = 4  # 同时向 embedding 服务发的请求数（每个请求 EMBEDDING_REQUEST_SIZE 条）
    INGEST_WRITE_BUFFER: int = 4  # 向量化完成、等待写库的批数上限：向量化与写库流水化，0 = 向量化完一批写一批
    EMBEDDING_REQUEST_SIZE: int = 20  # 单次 embedding 请求的条数上限（阿里云百炼 20；本地 oMLX 可更大）
    # Rerank 模型（FR-032）：provider 空 = 关闭（词法重排）；cohere = Cohere / Jina / TEI / vLLM / oMLX 共用的 POST /rerank；dashscope = 阿里云百炼
    RERANK_PROVIDER: str = ""
    RERANK_API_BASE: str = ""
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = ""
    RERANK_TIMEOUT: int = 5
    RERANK_CANDIDATES: int = 12  # 0.6B 重排 20 条 550 字要 1.6 秒，12 条约 1 秒；最终只取 top_k 4 条
    # 模型分阈值按 Qwen3-Reranker 实测标定：强相关 ≈ 0.99、弱相关 0.05～0.1、无关 < 0.01；宁可多留弱相关，提示词已要求不编造
    RERANK_MIN_SCORE: float = 0.02
    RERANK_GAP_RATIO: float = 0.02
    CHAT_TITLE_MAX_LEN: int = 30
    # 工作流 checkpointer 的连接池（docs/15 WF-12）。psycopg3 直连，与 SQLAlchemy 的 psycopg2 池分开：
    # 工作流执行线程最坏情况是"每个同时运行的工作流各占一个连接"，上限要挡住这个并发，不能按请求量拍。
    # 15 是折中：连云端共享库时一个进程多开 15 个连接会挤占 max_connections；超时给 10 秒，pool 耗尽要尽快暴露成失败，
    # 而不是让工作流排队等到前端超时（与 app/db/session.py 的 pool_timeout 同口径）。
    CHECKPOINT_POOL_MAX_SIZE: int = 15
    CHECKPOINT_POOL_TIMEOUT: int = 10
    # 工作流对外运行契约（docs/15 WF-05）：blocking 模式最多等这么多秒，超时只放弃等待、不取消执行，
    # 返回 202 + run_id 让调用方轮询（长流程不该被前端 30 秒超时打断）。
    WORKFLOW_BLOCKING_TIMEOUT_S: int = 60
    # 进程内同时执行的工作流上限（有界线程池 + 信号量）：满了 429，而不是把请求线程池或
    # checkpointer 连接池一起拖垮。与 CHECKPOINT_POOL_MAX_SIZE 一起决定最坏情况下的连接占用。
    WORKFLOW_MAX_CONCURRENCY: int = 4
    # 单条对话消息的字符上限：挡住超长输入刷 token 与成本；超出 422，在写消息、建运行记录之前拒绝
    CHAT_MESSAGE_MAX_CHARS: int = 8000
    # 非流式（blocking）对话的总超时秒数（docs/15 PB-10）：收齐全部事件才返回 JSON，
    # 所以必须有一个上界，否则上游一直不吐字时这个请求会挂到连接被中间设备掐断为止。
    # 取值要大于 MODEL_HTTP_TIMEOUT（单次模型调用 120 秒）+ 工具轮次，默认 300 秒；
    # 超时后把这一轮按"客户端中断"同一路径收尾（已生成内容落库、运行记录置 cancelled），再返回 504。
    CHAT_BLOCKING_TIMEOUT_SECONDS: int = 300
    # 运营统计按天分桶用的时区（工作台趋势图、按天聚合）；库里存的是 UTC，按业务所在时区切天才符合"今天"的直觉
    REPORT_TIMEZONE: str = "Asia/Shanghai"
    STATS_MAX_DAYS: int = 90
    # 一轮对话里模型最多请求几轮工具调用，超过即以错误结束、运行记录 failed（2026-09-25 前没接线，LangGraph 默认 10007 步）
    TOOL_CALL_MAX_ROUNDS: int = 8
    LOOP_MAX_ITERATIONS: int = 20
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # 联网搜索（内置 web_search 工具）：腾讯云 SearchPro 接口，key 不进代码库。
    # 留空则工具仍可见，但调用时返回"未配置"，不会静默失败成空结果。
    SEARCHPRO_KEY: str = ""
    SEARCHPRO_ENDPOINT: str = "https://api.wsa.cloud.tencent.com/SearchPro"
    TOOL_SEARCH_DEFAULT_LIMIT: int = 5
    TOOL_SEARCH_MAX_LIMIT: int = 10
    TOOL_SEARCH_TIMEOUT: int = 20
    # 内置 http_request 工具的域名白名单，逗号分隔，支持 *.example.com 后缀通配。
    # 留空 = 放行所有公网域名（内网地址段一律拦死，见 tools/general.py 的 SSRF 防护）。
    TOOL_HTTP_ALLOWED_HOSTS: str = ""
    TOOL_HTTP_TIMEOUT: int = 20
    TOOL_HTTP_MAX_BYTES: int = 200_000

    # 入口治理（FR-025 / FR-026）。列表类配置用字符串承载再自行拆分：
    # pydantic-settings 对 list 字段默认按 JSON 解析，.env 里写逗号分隔会直接报错。
    # CORS 只在浏览器直连后端时起作用；经同源反代（vite preview / nginx 的 /api 代理）不涉及。
    CORS_ORIGINS: str = "http://localhost:18056"
    # 全局 IP 黑名单：逗号分隔的 IP 或 CIDR，命中一律 403（/health 除外）
    IP_DENYLIST: str = ""
    # 只有后端确实在反向代理之后才能打开：打开后会信任 X-Real-IP / X-Forwarded-For，
    # 能直连后端的调用方就可以伪造来源 IP 绕过黑白名单
    TRUSTED_PROXY_ENABLED: bool = False
    # 对外地址（docs/15 PB-07）：分享链接、API 调用示例里给外部用的地址，如 https://agent.example.com。
    # 经 GET /auth/me 下发；留空时前端用浏览器当前访问的地址（经内网 IP 访问时生成的链接外部打不开，上线须配置）
    PUBLIC_BASE_URL: str = ""
    # 入口限流（FR-025）：按自然分钟固定窗口计数；总开关关闭或 Redis 不可用时放行并报降级。
    # 三个维度：API Key（单 Key 可覆盖）、登录用户、匿名 IP（仅登录接口）
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_API_KEY_PER_MINUTE: int = 60
    RATE_LIMIT_USER_PER_MINUTE: int = 300
    RATE_LIMIT_IP_PER_MINUTE: int = 20
    # Redis 故障时的降级方向（2026-11-18）：逗号分隔的 scope 名单，名单内 fail-closed（拒绝），名单外 fail-open（放行）。
    # 默认把公开入口（分享 share / 访客 share_v / 来源 IP ip）全部 fail-closed：
    # 这些入口不要求登录，Redis 一挂就等于对外完全无限流，成本与滥用风险直接暴露给公网；
    # 而内部接口（API Key ak / 登录用户 user）fail-open 更好 —— 它们背后是已经通过鉴权的可信调用方，
    # 因为限流组件故障把整站调用全部拒掉，等于用保护措施制造一次更大的故障。
    # 写成配置而不是写死：不同部署对"宁可拒绝还是宁可放行"的取舍不同，但要显式改，不能默认静默放开。
    RATE_LIMIT_FAIL_CLOSED_SCOPES: str = "share,share_v,ip"
    # 分享链接每位访客每分钟的对话次数（docs/15 3.6）；整条链接每分钟与每天的上限在每条分享上单独配
    SHARE_VISITOR_PER_MINUTE: int = 10

    # 定时任务的漏跑容忍窗口（秒）。APScheduler 默认 misfire_grace_time=1 秒：
    # 进程重启、调度线程被长任务占住超过 1 秒，那次触发就被直接丢弃，last_run_at 不变、也不留运行记录 ——
    # 使用者看到的是"任务配了但没跑"，服务端只有一行没人看的 debug 日志。
    # 60 秒是折中：够覆盖进程重启、GIL 抖动、一次短时 GC；又不会让"停机两小时后恢复"把积压的触发全补一遍
    # （coalesce=True 只补一次，不会雪崩）。要更宽容就调大，但别超过业务能接受的最大延迟。
    SCHEDULE_MISFIRE_GRACE_SECONDS: int = 60
    # 多实例选主（2026-11-18）：共享库 + 多后端进程时，只有抢到 PostgreSQL advisory lock 的实例
    # 注册并执行定时任务，避免同一条 cron 被每个进程各触发一次。
    # 单进程部署可以关掉（关掉等于"本进程必为主"）；测试里也关掉 ——
    # 开发库是共享的，本机跑着的后端会持有锁，pytest 进程就会变成"非主"，
    # 那样测出来的行为取决于别人有没有开服务，用例不可复现。
    SCHEDULER_LEADER_ELECTION_ENABLED: bool = True

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _check_cors_origins(cls, value: str) -> str:
        """每项必须是 * 或形如 http://host[:port] 的源（无路径、无末尾斜杠，否则永远匹配不上浏览器的 Origin）。

        配错在启动时就报错退出，不留到浏览器报跨域才发现。
        """
        for item in _split_csv(value):
            if item == "*":
                continue
            parts = urlsplit(item)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query or parts.fragment:
                raise ValueError(f"CORS_ORIGINS 含非法源 {item!r}，应形如 http://host:port")
        return value

    @field_validator("PUBLIC_BASE_URL")
    @classmethod
    def _check_public_base_url(cls, value: str) -> str:
        """空，或形如 https://host[:port][/前缀] 的地址；去掉末尾斜杠，前端直接拼 /s/xxx。配错启动即报错，不留到外部打不开链接才发现。"""
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
            raise ValueError(f"PUBLIC_BASE_URL 不是合法地址 {value!r}，应形如 https://agent.example.com")
        return value

    @field_validator("IP_DENYLIST")
    @classmethod
    def _check_ip_denylist(cls, value: str) -> str:
        """每项必须是合法 IP 或 CIDR；非法值启动即报错，而不是运行时静默不拦。"""
        for item in _split_csv(value):
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as e:
                raise ValueError(f"IP_DENYLIST 含非法 IP/CIDR {item!r}：{e}") from e
        return value

    @property
    def cors_origins(self) -> list[str]:
        return _split_csv(self.CORS_ORIGINS)

    @property
    def ip_denylist(self) -> list[str]:
        return _split_csv(self.IP_DENYLIST)


settings = Settings()
