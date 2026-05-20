"""FastAPI dependencies for the Archiver service."""

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.errors import raise_envelope
from src.core.database import get_session_factory
from src.core.models import ApiKey
from src.core.tools.fetch_and_render import HttpFetcherProtocol


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


def get_http_fetcher(request: Request) -> HttpFetcherProtocol:
    """Provide the lifespan-scoped HttpFetcher for tool routes.

    The fetcher is constructed once at app startup (see ``main.lifespan``) so
    its ``httpx.AsyncClient`` connection pool is shared across requests and
    closed cleanly on shutdown.

    Tests override this dependency with a no-arg callable, e.g.
    ``app.dependency_overrides[get_http_fetcher] = lambda: stub``. FastAPI
    invokes the override directly without re-resolving sub-deps, so the
    ``request: Request`` parameter is intentionally absent from the override
    signature — that's expected, not a mistake.
    """
    return request.app.state.http_fetcher


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
