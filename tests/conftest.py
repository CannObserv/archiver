"""Shared fixtures for Archiver service tests — async engine + httpx client."""

import asyncio
import hashlib
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ulid import ULID

from src.api.deps import get_db_session
from src.api.main import app

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


def _check_test_url_safety(test_url: str) -> None:
    """Raise if test_url matches any known production database URL.

    Prevents DROP SCHEMA ... CASCADE teardown from destroying production data
    when TEST_DATABASE_URL is accidentally set to a production connection string.
    """
    for var in ("ARCHIVER_DATABASE_URL", "DATABASE_URL"):
        prod_url = os.environ.get(var)
        if prod_url and test_url == prod_url:
            raise RuntimeError(
                f"TEST_DATABASE_URL must not equal {var}. "
                "Teardown runs DROP SCHEMA IF EXISTS information CASCADE "
                "and would destroy all production data. "
                "Set TEST_DATABASE_URL to a dedicated test database "
                "(database name should include '_test')."
            )


_check_test_url_safety(TEST_DATABASE_URL)

# Point the application itself at the test database for the whole session.
#
# The `client` fixture runs the real FastAPI lifespan, and anything resolving
# the URL from the environment rather than through the `get_db_session`
# override — get_engine() for the outbox publisher, alembic's get_url(), and
# the src.core.db_safety production guard — would otherwise read the
# *production* ARCHIVER_DATABASE_URL that .env supplies. Pinning it makes the
# override and the environment agree, and means a test can never reach
# production even if it bypasses the dependency override.
#
# DATABASE_URL is cleared because src.core.database falls back to it.
#
# This runs at import rather than in a fixture because it must be in place
# before *any* fixture resolves the URL, and it is deliberately not restored:
# the value is process-scoped, the process exists only to run this suite, and
# a restore would hand the production URL back to whatever ran last. Under
# pytest-xdist each worker is a separate process that imports this module, so
# every worker gets its own pin.
#
# This is the single mechanism managing these two variables. `_run_alembic_upgrade`
# used to save/restore them independently; with the pin in place that was a
# no-op wrapped around a no-op, and two mechanisms owning one variable is how
# they drift.
os.environ["ARCHIVER_DATABASE_URL"] = TEST_DATABASE_URL
os.environ.pop("DATABASE_URL", None)


def _run_alembic_upgrade() -> None:
    """Run alembic upgrade head against TEST_DATABASE_URL.

    Must execute in a thread (via run_in_executor) because alembic/env.py
    calls asyncio.run() internally, which conflicts with a running event loop.
    alembic's get_url() reads ARCHIVER_DATABASE_URL, which the module-level pin
    above has already set to the test database.
    """
    cfg = AlembicConfig(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def test_engine():
    # Run the full migration chain in a thread — alembic calls asyncio.run()
    # internally, which requires a thread with no existing event loop.
    # Migrations handle: information schema creation, pg_trgm extension,
    # all table DDL, constraints, and indexes.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_alembic_upgrade)

    engine = create_async_engine(TEST_DATABASE_URL)

    # Seed a test API key so require_api_key DB lookup succeeds for all
    # tests that send X-API-Key: test-secret-key.
    async with engine.begin() as conn:
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
        # drops the FK constraint along with the InfoItem tables.
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


@pytest.fixture
async def committed_rows(test_engine) -> AsyncGenerator[list]:
    """Track rows a test really COMMITs, and delete them on teardown.

    Nearly every test runs inside the SAVEPOINT-scoped ``session`` fixture and
    rolls back automatically. A few can't — row-lock behaviour is only
    observable across independent connections, which means real commits. Those
    rows are visible to every other test in the run, and several assert exact
    page sizes over global listings (see tests/api/test_rep_specs.py pagination
    tests), so a leak surfaces as a confusing failure in an unrelated module.

    Usage: append ``(Model, primary_key)`` pairs as you commit them. Deletion is
    LIFO so children go before parents.
    """
    tracked: list = []
    yield tracked

    if not tracked:
        return
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as s:
        for model, pk in reversed(tracked):
            obj = await s.get(model, pk)
            if obj is not None:
                await s.delete(obj)
        await s.commit()
