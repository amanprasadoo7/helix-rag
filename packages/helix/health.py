"""Readiness checks for external dependencies.

Each check is deliberately short-lived and bounded by a timeout. A readiness
probe must answer quickly even when a dependency is unreachable, otherwise
orchestrators cannot tell the difference between "slow" and "dead".
"""

import asyncio
from typing import Literal

import asyncpg
import httpx
import redis.asyncio as redis
import structlog
from qdrant_client import AsyncQdrantClient

from helix.config import Settings, get_settings

CheckStatus = Literal["ok", "down"]

CHECK_TIMEOUT_SECONDS = 1.5

logger = structlog.get_logger()


async def check_postgres(settings: Settings) -> CheckStatus:
    try:
        connection = await asyncpg.connect(
            settings.postgres_dsn,
            timeout=CHECK_TIMEOUT_SECONDS,
        )
        try:
            await connection.fetchval("SELECT 1")
        finally:
            await connection.close()
    except Exception as exc:  # readiness must never raise
        logger.debug("postgres_ready_failed", error=type(exc).__name__)
        return "down"
    return "ok"


async def check_redis(settings: Settings) -> CheckStatus:
    try:
        client = redis.from_url(
            settings.redis_url,
            socket_connect_timeout=CHECK_TIMEOUT_SECONDS,
            socket_timeout=CHECK_TIMEOUT_SECONDS,
        )
        try:
            await client.ping()
        finally:
            await client.aclose()
    except Exception as exc:  # readiness must never raise
        logger.debug("redis_ready_failed", error=type(exc).__name__)
        return "down"
    return "ok"


async def check_qdrant(settings: Settings) -> CheckStatus:
    try:
        client = AsyncQdrantClient(
            url=settings.qdrant_url,
            timeout=int(CHECK_TIMEOUT_SECONDS),
        )
        try:
            await client.get_collections()
        finally:
            await client.close()
    except Exception as exc:  # readiness must never raise
        logger.debug("qdrant_ready_failed", error=type(exc).__name__)
        return "down"
    return "ok"


async def check_minio(settings: Settings) -> CheckStatus:
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{settings.minio_endpoint}/minio/health/live")
            response.raise_for_status()
    except Exception as exc:  # readiness must never raise
        logger.debug("minio_ready_failed", error=type(exc).__name__)
        return "down"
    return "ok"


async def check_readiness(settings: Settings | None = None) -> dict[str, CheckStatus]:
    """Check all dependencies concurrently and return a stable report."""
    resolved = settings or get_settings()

    results = await asyncio.gather(
        check_postgres(resolved),
        check_redis(resolved),
        check_qdrant(resolved),
        check_minio(resolved),
    )

    names = ("postgres", "redis", "qdrant", "minio")
    return dict(zip(names, results, strict=True))
