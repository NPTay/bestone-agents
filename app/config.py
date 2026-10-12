from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env (names per docs/06)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: int = 120
    MODEL_QUALITY: str = "claude-sonnet-5-5"
    MODEL_FAST: str = "claude-haiku-5-5"
    DAILY_COST_LIMIT_USD: str = ""

    # Meta
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_PAGE_ID: str = ""
    META_PAGE_ACCESS_TOKEN: str = ""
    META_VERIFY_TOKEN: str = ""
    META_GRAPH_VERSION: str = ""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_CHAT_ID: str = ""

    # SMTP / alerts
    SMTP_HOST: str = ""
    SMTP_PORT: str = ""
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    ALERT_EMAIL_TO: str = ""
    SEARCH_API_KEY: str = ""

    # Database
    POSTGRES_DB: str = "bestone"
    POSTGRES_USER: str = "bestone_app"
    POSTGRES_PASSWORD: str = ""
    DATABASE_URL: str

    # Sessions / auth
    SESSION_SECRET_KEY: str
    SESSION_COOKIE_NAME: str = "bestone_session"
    SESSION_MAX_AGE_SECONDS: int = 28800
    SESSION_REMEMBER_DAYS: int = 30
    INITIAL_ADMIN_USERNAME: str = ""
    INITIAL_ADMIN_PASSWORD: str = ""

    # Backup (S3-compatible)
    BACKUP_S3_ENDPOINT: str = ""
    BACKUP_S3_BUCKET: str = ""
    BACKUP_S3_ACCESS_KEY: str = ""
    BACKUP_S3_SECRET_KEY: str = ""

    # Runtime
    APP_ENV: Literal["dev", "prod"] = "prod"
    APP_DOMAIN: str = ""
    TRUSTED_PROXY_IPS: str = "127.0.0.1"
    AUTONOMY_LEVEL: str = "draft_only"
    TZ: str = "Asia/Ho_Chi_Minh"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
