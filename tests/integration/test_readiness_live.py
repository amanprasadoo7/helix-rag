"""Integration test: requires `make up` and the real local services."""

import pytest
from apps.api.main import app
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_readiness_against_the_live_stack() -> None:
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200, response.text
    assert response.json()["checks"] == {
        "postgres": "ok",
        "redis": "ok",
        "qdrant": "ok",
        "minio": "ok",
    }
