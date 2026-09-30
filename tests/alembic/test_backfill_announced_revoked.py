"""The archiver#293 ``announced_revoked`` backfill (``d3f9a6b8e015``).

The column lands ``false`` everywhere, which is wrong for every row whose last
announcement was a tombstone: the next binding mutation that leaves one
unannounceable would re-tombstone it once more. The backfill sets ``true`` on
exactly the rows the snapshot tombstones today - ``announcement_generation > 0``
and no active binding to a source with non-empty ``source_specs`` - so the flag
and the full set agree from the first deploy.

Drives the migration module's ``upgrade()`` under a real ``MigrationContext``
rather than re-typing its SQL, as the #161 floor backfill test does.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import InfoItem, InfoItemSource, InfoSource

_MIGRATION = (
    Path(__file__).parent.parent.parent
    / "alembic"
    / "versions"
    / "d3f9a6b8e015_backfill_announced_revoked.py"
)

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]


def _load_migration():
    spec = importlib.util.spec_from_file_location("_backfill_announced_revoked", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def clean_items(test_engine):
    async def _clean():
        async with test_engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE information.info_item_sources"))
            await conn.execute(text("DELETE FROM information.info_items"))
            await conn.execute(text("DELETE FROM information.info_sources"))

    await _clean()
    yield
    await _clean()


async def _run_upgrade(test_engine) -> None:
    module = _load_migration()

    def _apply(sync_conn):
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            module.upgrade()

    async with test_engine.begin() as conn:
        await conn.run_sync(_apply)


async def _item(session, name: str, *, generation: int, specs: list | None = None) -> InfoItem:
    """An item at ``generation``; bound to a source with ``specs`` unless None."""
    item = InfoItem(name=name, announcement_generation=generation)
    session.add(item)
    await session.flush()
    if specs is not None:
        source = InfoSource(url=f"https://example.test/{name}", source_specs=specs)
        session.add(source)
        await session.flush()
        session.add(
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
        )
        await session.flush()
    return item


async def _flags(session_factory) -> dict[str, bool]:
    async with session_factory() as s:
        rows = (
            await s.execute(text("SELECT name, announced_revoked FROM information.info_items"))
        ).all()
    return dict(rows)


@pytest.mark.asyncio
async def test_rows_the_snapshot_tombstones_are_marked_revoked(test_engine, session_factory):
    """Unbound, or bound to a spec-less source, after having been announced."""
    async with session_factory() as s:
        await _item(s, "unbound", generation=3)
        await _item(s, "specless", generation=2, specs=[])
        await s.commit()

    await _run_upgrade(test_engine)

    assert await _flags(session_factory) == {"unbound": True, "specless": True}


@pytest.mark.asyncio
async def test_a_deactivated_binding_does_not_count_as_live(test_engine, session_factory):
    """``deactivated_at`` is the snapshot's own liveness test."""
    async with session_factory() as s:
        item = await _item(s, "detached", generation=2, specs=_SPECS)
        result = await s.execute(
            text(
                "UPDATE information.info_item_sources SET deactivated_at = :now"
                " WHERE info_item_id = :id"
            ),
            {"now": datetime.now(UTC), "id": str(item.info_item_id)},
        )
        assert result.rowcount == 1
        await s.commit()

    await _run_upgrade(test_engine)

    assert (await _flags(session_factory))["detached"] is True


@pytest.mark.asyncio
async def test_live_and_never_announced_rows_stay_false(test_engine, session_factory):
    """A live row's last announcement was live; a gen-0 row has none at all.

    Marking a never-announced row revoked would be harmless to the skip (gen 0
    already skips) but would make the flag lie about a key no consumer holds.
    """
    async with session_factory() as s:
        await _item(s, "live", generation=4, specs=_SPECS)
        await _item(s, "never", generation=0)
        await _item(s, "never-specless", generation=0, specs=[])
        await s.commit()

    await _run_upgrade(test_engine)

    assert await _flags(session_factory) == {
        "live": False,
        "never": False,
        "never-specless": False,
    }


@pytest.mark.asyncio
async def test_the_backfill_is_idempotent(test_engine, session_factory):
    async with session_factory() as s:
        await _item(s, "unbound", generation=3)
        await _item(s, "live", generation=4, specs=_SPECS)
        await s.commit()

    await _run_upgrade(test_engine)
    first = await _flags(session_factory)
    await _run_upgrade(test_engine)

    assert await _flags(session_factory) == first == {"unbound": True, "live": False}
