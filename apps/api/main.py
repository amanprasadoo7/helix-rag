"""Helix HTTP API.

Checkpoint 0.1 only exposes liveness. Readiness (real dependency checks) is
added in 0.2 once Postgres, Redis, Qdrant, and MinIO exist.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from helix.config import get_settings
from helix.health import check_readiness
from helix.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level, json_logs=settings.app_env in {"staging", "prod"})
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("api_started", env=settings.app_env, version=settings.app_version)
    yield
    logger.info("api_stopped")


app = FastAPI(title="Helix API", version=settings.app_version, lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "health": "/health/live",
    }


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    """Liveness: the process is up and serving requests."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/health/ready", tags=["health"])
async def readiness() -> JSONResponse:
    """Readiness: every dependency needed to answer requests is reachable."""
    checks = await check_readiness()
    healthy = all(status == "ok" for status in checks.values())

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "service": settings.app_name,
            "checks": checks,
        },
    )
