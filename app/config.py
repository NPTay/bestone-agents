from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Desktop settings loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: int = 120
    MODEL_QUALITY: str = "claude-sonnet-5-5"
    MODEL_FAST: str = "claude-haiku-5-5"

    # Meta
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_PAGE_ID: str = ""
    META_PAGE_ACCESS_TOKEN: str = ""
    META_GRAPH_VERSION: str = "v26.0"

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_CHAT_ID: str = ""

    # Images
    PEXELS_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_IMAGE_MODEL: str = "gemini-3.1-flash-image"

    # Storage
    DATABASE_URL: str = "sqlite:///data/bestone.db"
    DATA_DIR: str = "data"
    PICTURE_DIR: str = "Picture"
    DOCS_DIR: str = "Tai Lieu"

    # Runtime
    DASHBOARD_PORT: int = 8765
    DRY_RUN: bool = True
    TZ: str = "Asia/Ho_Chi_Minh"


@lru_cache
def get_settings() -> Settings:
    return Settings()
