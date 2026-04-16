from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    log_level: str

    postgres_dsn: str
    redis_url: str

    model_provider: str
    model_name: str
    model_api_key: str
    model_timeout_seconds: int

    feature_enable_writeback: bool
    feature_enable_inspection_agent: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "eLicense API"),
        app_env=os.getenv("APP_ENV", "dev"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        postgres_dsn=os.getenv(
            "POSTGRES_DSN", "postgresql://user:password@localhost:5432/elicense"
        ),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        model_provider=os.getenv("MODEL_PROVIDER", "openai"),
        model_name=os.getenv("MODEL_NAME", "gpt-4.1-mini"),
        model_api_key=os.getenv("MODEL_API_KEY", ""),
        model_timeout_seconds=int(os.getenv("MODEL_TIMEOUT_SECONDS", "30")),
        feature_enable_writeback=_bool_env("FEATURE_ENABLE_WRITEBACK", default=False),
        feature_enable_inspection_agent=_bool_env(
            "FEATURE_ENABLE_INSPECTION_AGENT", default=False
        ),
    )
