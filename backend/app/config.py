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
    RAG_TOP_K: int = 4
    CHAT_HISTORY_MAX_MESSAGES: int = 20
    CHAT_TITLE_MAX_LEN: int = 30
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
