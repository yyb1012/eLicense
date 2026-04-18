# Time: 2026-04-19 00:14
# Description: 从环境变量加载并缓存运行时配置，统一管理模型、OCR、持久化与文档入库参数。
# Author: Feixue

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool_env(name: str, default: bool = False) -> bool:
    """读取布尔环境变量，兼容常见真值写法。"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    """读取整数环境变量，解析失败时回退默认值。"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """应用运行时配置聚合对象。"""

    app_name: str
    app_env: str
    log_level: str

    postgres_dsn: str
    redis_url: str
    object_storage_endpoint: str

    model_provider: str
    model_name: str
    model_api_key: str
    model_timeout_seconds: int

    ingest_store_sqlite_path: str
    ingest_chunk_max_tokens: int
    ingest_chunk_max_chars: int
    ingest_chunk_overlap: int

    ingest_embedding_provider: str
    ingest_embedding_model: str
    ingest_embedding_dimension: int
    ingest_embedding_timeout_seconds: int
    ingest_embedding_max_retries: int
    ingest_embedding_batch_size: int
    ingest_embedding_version: str

    ocr_provider: str
    ocr_enabled: bool

    feature_enable_writeback: bool
    feature_enable_inspection_agent: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载并缓存配置，避免同一进程重复读取环境变量。"""
    return Settings(
        app_name=os.getenv("APP_NAME", "eLicense API"),
        app_env=os.getenv("APP_ENV", "dev"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        postgres_dsn=os.getenv(
            "POSTGRES_DSN", "postgresql://user:password@localhost:5432/elicense"
        ),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        object_storage_endpoint=os.getenv(
            "OBJECT_STORAGE_ENDPOINT", "http://localhost:9000"
        ),
        model_provider=os.getenv("MODEL_PROVIDER", "openai"),
        model_name=os.getenv("MODEL_NAME", "gpt-5.4-mini"),
        model_api_key=os.getenv("MODEL_API_KEY", ""),
        model_timeout_seconds=_int_env("MODEL_TIMEOUT_SECONDS", 30),
        ingest_store_sqlite_path=os.getenv("INGEST_STORE_SQLITE_PATH", ".runtime/document_ingest.db"),
        ingest_chunk_max_tokens=_int_env(
            "INGEST_CHUNK_MAX_TOKENS",
            _int_env("INGEST_CHUNK_SIZE", 500),
        ),
        ingest_chunk_max_chars=_int_env("INGEST_CHUNK_MAX_CHARS", 2400),
        ingest_chunk_overlap=_int_env("INGEST_CHUNK_OVERLAP", 80),
        ingest_embedding_provider=os.getenv("INGEST_EMBEDDING_PROVIDER", "openai"),
        ingest_embedding_model=os.getenv("INGEST_EMBEDDING_MODEL", "text-embedding-3-small"),
        ingest_embedding_dimension=_int_env("INGEST_EMBEDDING_DIMENSION", 1536),
        ingest_embedding_timeout_seconds=_int_env("INGEST_EMBEDDING_TIMEOUT_SECONDS", 20),
        ingest_embedding_max_retries=_int_env("INGEST_EMBEDDING_MAX_RETRIES", 2),
        ingest_embedding_batch_size=_int_env("INGEST_EMBEDDING_BATCH_SIZE", 16),
        ingest_embedding_version=os.getenv("INGEST_EMBEDDING_VERSION", "v1"),
        ocr_provider=os.getenv("OCR_PROVIDER", "paddleocr"),
        ocr_enabled=_bool_env("OCR_ENABLED", default=True),
        feature_enable_writeback=_bool_env("FEATURE_ENABLE_WRITEBACK", default=False),
        feature_enable_inspection_agent=_bool_env(
            "FEATURE_ENABLE_INSPECTION_AGENT", default=False
        ),
    )

