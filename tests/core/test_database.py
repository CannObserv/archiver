"""The app engine: ``get_database_url``'s refusal (#452 D5), the pre-ping (#510),
and the start line that names the database without its credentials (#448)."""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.core.database import get_database_url, get_engine, loggable_url, reset_engine

SENTINEL = "Zq7sent%40Kx9col%3AWm4pct%25Vb2end"


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("postgresql+asyncpg://u:p@localhost:5432/archiver_test", "localhost:5432/archiver_test"),
        (f"postgresql+asyncpg://u:{SENTINEL}@db.internal/archiver", "db.internal/archiver"),
        # libpq and asyncpg both take ?password=: no query value is logged.
        (
            f"postgresql+asyncpg://u@localhost:5432/archiver_test?password={SENTINEL}",
            "localhost:5432/archiver_test?***",
        ),
        ("postgresql+asyncpg://u:p@[::1]:5432/archiver_test", "[::1]:5432/archiver_test"),
        # A socket URL names its host in the query; the database still shows.
        ("postgresql+asyncpg://u:p@/archiver?host=/var/run/postgresql", "/archiver?***"),
    ],
)
def test_loggable_url_names_the_target_and_never_a_credential(url: str, shown: str) -> None:
    assert loggable_url(make_url(url)) == shown


def test_the_engine_start_line_carries_no_query_password(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``url.split("@")[-1]`` kept the query, ``?password=`` included (#448 CR 1)."""
    monkeypatch.setenv(
        "ARCHIVER_DATABASE_URL",
        f"postgresql+asyncpg://u@localhost:5432/archiver_test?password={SENTINEL}",
    )
    reset_engine()
    try:
        with caplog.at_level(logging.INFO, logger="src.core.database"):
            get_engine()
    finally:
        reset_engine()
    (record,) = [r for r in caplog.records if r.getMessage() == "archiver db engine created"]
    assert record.url == "localhost:5432/archiver_test?***"
    assert "Zq7sent" not in caplog.text


def test_a_missing_url_points_at_the_env_files_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCHIVER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        get_database_url()
    message = str(excinfo.value)
    assert "AGENTS.md § Environment Files" in message
    assert "/etc/archiver/.env" in message, "production's is the units'"
    assert ". .env" not in message, "no shell recipe to copy"


@pytest.fixture
async def app_engine():
    """The engine ``get_engine()`` builds, fresh, on the pinned test database.

    The suite's ``session`` fixture binds its own ``test_engine``, so an option
    set in ``get_engine()`` is only visible through ``get_engine()`` itself.
    """
    reset_engine()
    engine = get_engine()
    try:
        yield engine
    finally:
        await engine.dispose()
        reset_engine()


async def test_a_pooled_connection_killed_while_idle_costs_no_request(app_engine, test_engine):
    """A Postgres restart kills every idle pooled connection; the next checkout must not fail.

    Reproduced without a restart (the cluster is production's too): the test
    role terminates its own idle backend, which a role may do without
    ``pg_signal_backend``. Without ``pool_pre_ping`` the next checkout hands
    back the dead connection and the first statement raises.
    """
    async with app_engine.connect() as conn:
        dead_pid = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
    # Back in the pool, idle. Kill it, and wait (PG 14+) until it is gone.
    async with test_engine.connect() as killer:
        killed = await killer.execute(
            text("SELECT pg_terminate_backend(:pid, 5000)"), {"pid": dead_pid}
        )
        assert killed.scalar_one() is True

    async with app_engine.connect() as conn:
        pid = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()

    assert pid != dead_pid, "the pool handed back a fresh connection"
