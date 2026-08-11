from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.core.auth import AuthManager
from src.main import app


TEST_API_KEY = "contract-test-api-key"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_API_KEY}"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """An in-process client which deliberately does not run the app lifespan.

    The production lifespan opens the real database and starts browser-related
    background services.  Contract tests only need the already-registered ASGI
    routes, so TestClient is not used as a context manager here.
    """

    monkeypatch.setattr(
        AuthManager,
        "verify_api_key",
        staticmethod(lambda value: value == TEST_API_KEY),
    )
    test_client = TestClient(app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        test_client.close()
