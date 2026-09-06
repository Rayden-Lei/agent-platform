import ipaddress
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    """逗号分隔的环境变量 → 去空白、去空项的列表。"""
    return [v.strip() for v in (value or "").split(",") if v.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Agent Platform"
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    AES_KEY: str = "change-me-32-bytes-key"
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/agent_platform"
    REDIS_URL: str = "redis://localhost:6379/0"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "kb-docs"
    MODEL_HTTP_TIMEOUT: int = 120
    # 模型调用熔断（FR-027）。SDK 重试归零：故障处理统一交给熔断器；阈值 0 表示关闭熔断
    MODEL_MAX_RETRIES: int = 0
    MODEL_BREAKER_FAIL_THRESHOLD: int = 5
    MODEL_BREAKER_OPEN_SECONDS: int = 30
    RAG_TOP_K: int = 4
    CHAT_HISTORY_MAX_MESSAGES: int = 20
    # 对话摘要持久化（FR-031）：更早消息里未折叠进摘要的攒够这么多条才调一次模型，不足时按原文注入
    CHAT_SUMMARY_BATCH_MESSAGES: int = 10
    # RAG 查询改写：默认关闭。开启后每条消息多一次模型调用（DeepSeek 类模型实测 4～9 秒），只在召回质量明显不足时打开
    RAG_QUERY_REWRITE_ENABLED: bool = False
    RAG_QUERY_REWRITE_TIMEOUT_SECONDS: int = 3
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
    # 运营统计按天分桶用的时区（工作台趋势图、按天聚合）；库里存的是 UTC，按业务所在时区切天才符合"今天"的直觉
    REPORT_TIMEZONE: str = "Asia/Shanghai"
    STATS_MAX_DAYS: int = 90
    TOOL_CALL_MAX_ROUNDS: int = 8
    LOOP_MAX_ITERATIONS: int = 20
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # 入口治理（FR-025 / FR-026）。列表类配置用字符串承载再自行拆分：
    # pydantic-settings 对 list 字段默认按 JSON 解析，.env 里写逗号分隔会直接报错。
    # CORS 只在浏览器直连后端时起作用；经同源反代（vite preview / nginx 的 /api 代理）不涉及。
    CORS_ORIGINS: str = "http://localhost:18056"
    # 全局 IP 黑名单：逗号分隔的 IP 或 CIDR，命中一律 403（/health 除外）
    IP_DENYLIST: str = ""
    # 只有后端确实在反向代理之后才能打开：打开后会信任 X-Real-IP / X-Forwarded-For，
    # 能直连后端的调用方就可以伪造来源 IP 绕过黑白名单
    TRUSTED_PROXY_ENABLED: bool = False
    # 入口限流（FR-025）：按自然分钟固定窗口计数；总开关关闭或 Redis 不可用时放行并报降级。
    # 三个维度：API Key（单 Key 可覆盖）、登录用户、匿名 IP（仅登录接口）
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_API_KEY_PER_MINUTE: int = 60
    RATE_LIMIT_USER_PER_MINUTE: int = 300
    RATE_LIMIT_IP_PER_MINUTE: int = 20

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
