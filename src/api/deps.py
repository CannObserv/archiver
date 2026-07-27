"""FastAPI dependencies for the Archiver service."""

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from co_core_aio.fetch import AsyncFetchDriver
from fastapi import Depends, Request
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.errors import raise_envelope
from src.core.database import get_session_factory
from src.core.models import ApiKey

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisAsync
    from watcher_client import WatcherClient


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def get_redis_client(request: Request) -> "RedisAsync | None":
    """Return the lifespan-scoped Redis client, or None when not configured."""
    return getattr(request.app.state, "redis_client", None)


async def get_watcher_client(request: Request) -> "WatcherClient | None":
    """Return the lifespan-scoped WatcherClient, or None when Watcher is not configured.

    None is returned when ``WATCHER_BASE_URL`` / ``WATCHER_API_KEY`` are unset.
    Routes that accept this dependency treat None as "provisioning disabled".
    """
    return getattr(request.app.state, "watcher_client", None)


async def get_fetch_driver(request: Request) -> AsyncFetchDriver:
    """Provide the lifespan-scoped ``AsyncFetchDriver`` for tool routes.

    The driver is constructed once at app startup (see ``main.lifespan``) so
    its ``httpx.AsyncClient`` connection pool is shared across requests and
    closed cleanly on shutdown.

    Tests override this dependency with a no-arg callable, e.g.
    ``app.dependency_overrides[get_fetch_driver] = lambda: stub``. FastAPI
    invokes the override directly without re-resolving sub-deps, so the
    ``request: Request`` parameter is intentionally absent from the override
    signature — that's expected, not a mistake.
    """
    return request.app.state.fetch_driver


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    raw_key: str | None = Depends(api_key_header),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Validate X-API-Key via SHA-256 hash lookup against information.api_keys.

    Raises 403 when the header is absent and 401 when no matching key is found.
    Updates last_used_at on the matched row.
    """
    if raw_key is None:
        raise_envelope(403, "auth", "Not authenticated")
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == hashlib.sha256(raw_key.encode()).hexdigest())
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise_envelope(401, "auth", "Invalid API key")
    api_key.last_used_at = datetime.now(UTC)
    await session.flush()
