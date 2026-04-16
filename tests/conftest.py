from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.interfaces.api.main import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
