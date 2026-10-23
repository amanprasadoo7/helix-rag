import pytest
from apps.api import main
from apps.api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_liveness_returns_ok() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "helix-api"
    assert body["version"] == "0.1.0"


def test_root_points_at_docs_and_health() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "helix-api",
        "docs": "/docs",
        "health": "/health/live",
    }


def test_unknown_route_returns_404() -> None:
    assert client.get("/does-not-exist").status_code == 404


def test_ready_returns_200_when_all_dependencies_are_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = {"postgres": "ok", "redis": "ok", "qdrant": "ok", "minio": "ok"}

    async def all_ok() -> dict[str, str]:
        return checks

    monkeypatch.setattr(main, "check_readiness", all_ok)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "helix-api",
        "checks": checks,
    }


def test_ready_returns_503_when_a_dependency_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = {"postgres": "ok", "redis": "ok", "qdrant": "down", "minio": "ok"}

    async def qdrant_down() -> dict[str, str]:
        return checks

    monkeypatch.setattr(main, "check_readiness", qdrant_down)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["qdrant"] == "down"
