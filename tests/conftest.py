# Time: 2026-04-19 00:50
# Description: 提供通用 pytest fixture（含 FastAPI 测试客户端与环境隔离），确保测试运行不依赖外部服务。
# Author: Feixue

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.interfaces.api.main import create_app
from src.shared import logger as logger_mod
from src.shared.config import get_settings


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    # 隔离测试环境：向量化走本地确定性 provider，入库走临时 sqlite 路径。
    patched_env = {
        "INGEST_EMBEDDING_PROVIDER": "deterministic",
        "INGEST_EMBEDDING_DIMENSION": "16",
        "INGEST_STORE_SQLITE_PATH": str(tmp_path / "document_ingest_test.db"),
        "INGEST_CHUNK_MAX_TOKENS": "80",
        "INGEST_CHUNK_MAX_CHARS": "600",
        "INGEST_CHUNK_OVERLAP": "10",
        "OCR_ENABLED": "true",
    }
    original_env: dict[str, str | None] = {key: os.getenv(key) for key in patched_env}
    for key, value in patched_env.items():
        os.environ[key] = value

    get_settings.cache_clear()
    logger_mod._LOGGING_READY = False

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    get_settings.cache_clear()
    logger_mod._LOGGING_READY = False
