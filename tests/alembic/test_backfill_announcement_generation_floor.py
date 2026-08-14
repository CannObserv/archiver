"""The archiver#161 generation floor backfill (``e3a71c40b9d2``).

The conftest runs the whole chain against an empty database, so the chain
passing proves only that the statement parses. What needs pinning is what it
does to *data*: every un-bumped row moves to 1, no already-announced row moves,
and a re-run is a no-op. Drives the migration module's ``upgrade()`` under a
real ``MigrationContext`` rather than re-typing its SQL — a copy of the
statement in the test would pass while the migration itself drifted.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import InfoItem

_MIGRATION = (
    Path(__file__).parent.parent.parent
    / "alembic"
    / "versions"
    / "e3a71c40b9d2_backfill_announcement_generation_floor.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_backfill_gen_floor", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def clean_items(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM information.info_items"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM information.info_items"))


async def _run_upgrade(test_engine) -> None:
    module = _load_migration()

    def _apply(sync_conn):
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            module.upgrade()

    async with test_engine.begin() as conn:
        await conn.run_sync(_apply)


async def _generations(session_factory) -> dict[str, tuple[int, bool]]:
    async with session_factory() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT name, announcement_generation, announced_at IS NOT NULL"
                    "  FROM information.info_items"
                )
            )
        ).all()
    return {name: (gen, stamped) for name, gen, stamped in rows}


@pytest.mark.asyncio
async def test_only_generation_zero_moves_and_carries_a_stamp(test_engine, session_factory):
    """Un-bumped rows lift to 1 with a clock; announced rows are untouched.

    The stamp matters as much as the counter: ``_drift`` dates announcement lag
    from ``announced_at``, so a bumped generation with a NULL stamp would render
    as drift of unknown age.
    """
    async with session_factory() as s:
        s.add_all(
            [
                InfoItem(name="legacy", announcement_generation=0),
                InfoItem(name="announced", announcement_generation=7),
            ]
        )
        await s.commit()

    await _run_upgrade(test_engine)

    after = await _generations(session_factory)
    assert after["legacy"] == (1, True)
    assert after["announced"][0] == 7


@pytest.mark.asyncio
async def test_the_backfill_is_idempotent(test_engine, session_factory):
    """Re-running matches nothing — the second pass must not lift a real 1 to 2.

    An operator re-runs migrations; a backfill that advanced on every pass would
    manufacture announcements out of ``alembic upgrade head``.
    """
    async with session_factory() as s:
        s.add(InfoItem(name="legacy", announcement_generation=0))
        await s.commit()

    await _run_upgrade(test_engine)
    first = await _generations(session_factory)
    await _run_upgrade(test_engine)
    second = await _generations(session_factory)

    assert first["legacy"][0] == 1
    assert second["legacy"][0] == 1
