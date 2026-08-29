from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
