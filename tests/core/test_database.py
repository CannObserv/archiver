"""The app engine: ``get_database_url``'s refusal (#452 D5) and the pre-ping (#510)."""

import pytest
from sqlalchemy import text

from src.core.database import get_database_url, get_engine, reset_engine


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
