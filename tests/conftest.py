"""Shared fixtures for Archiver service tests — async engine + httpx client."""

import hashlib
import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ulid import ULID

from src.api.deps import get_db_session
from src.api.main import app
from src.core.models import Base

# ---------------------------------------------------------------------------
# Test API key — seeded once per session; all existing tests send this value.
# After Epic 2, require_api_key does a DB hash lookup instead of env-var check.
# ---------------------------------------------------------------------------
_TEST_API_KEY_RAW = "test-secret-key"
_TEST_API_KEY_HASH = hashlib.sha256(_TEST_API_KEY_RAW.encode()).hexdigest()

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. "
        "Load env: set -a; "
        "[ -f /etc/archiver/.env ] && . /etc/archiver/.env; "
        "[ -f .env ] && . .env; set +a"
    )


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        # Ensure the information schema exists before create_all binds tables to it.
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS information"))
        # Required for the GIN trigram indexes on info_items.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
        # Seed a test API key so require_api_key DB lookup succeeds for all
        # tests that send X-API-Key: test-secret-key.
        user_id = str(ULID())
        key_id = str(ULID())
        await conn.execute(
            text(
                "INSERT INTO information.app_users"
                " (id, external_id, email, created_at, updated_at)"
                " VALUES (:id, :ext_id, :email, now(), now())"
            ),
            {"id": user_id, "ext_id": "test-api-user", "email": "api-test@system.internal"},
        )
        await conn.execute(
            text(
                "INSERT INTO information.api_keys"
                " (id, user_id, label, key_prefix, key_hash, created_at)"
                " VALUES (:id, :user_id, :label, :key_prefix, :key_hash, now())"
            ),
            {
                "id": key_id,
                "user_id": user_id,
                "label": "Test key (seeded by conftest)",
                "key_prefix": _TEST_API_KEY_RAW[:8],
                "key_hash": _TEST_API_KEY_HASH,
            },
        )
    yield engine
    async with engine.begin() as conn:
        # The Watcher test conftest may have created ``public.watches`` with
        # an FK to ``information.info_items``; ``DROP SCHEMA ... CASCADE``
        # drops the FK constraint along with the InfoItem tables. Skip
        # ``Base.metadata.drop_all`` since CASCADE handles the InformationBase
        # tables directly.
        await conn.execute(text("DROP SCHEMA IF EXISTS information CASCADE"))
    await engine.dispose()


@pytest.fixture
async def session(test_engine) -> AsyncGenerator[AsyncSession]:
    # Use a nested (SAVEPOINT) transaction so that handler-level commits are
    # contained and the whole test rolls back on teardown.
    async with test_engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()  # SAVEPOINT
        factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with factory() as s:
            yield s
        await conn.rollback()


@pytest.fixture
async def client(test_engine, session) -> AsyncGenerator[AsyncClient]:
    async def _override_session():
        yield session

    app.dependency_overrides[get_db_session] = _override_session
    # Run the FastAPI lifespan so app.state.http_fetcher is populated for tool
    # routes whose dependency injects it (even when the route itself short-
    # circuits before fetching — FastAPI resolves the dep before the handler).
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    app.dependency_overrides.clear()
