"""The archiver#161 generation floor backfill (``e3a71c40b9d2``).

The conftest runs the whole chain against an empty database, so the chain
passing proves only that the statement parses. What needs pinning is what it
does to *data* — and specifically its **scope**, which is narrower than "every
un-bumped row". Only a row the snapshot would publish *live* can put a 0 on the
wire; a row that is unbound, or bound to a spec-less source, is filtered out of
both revoked lists by their own ``announcement_generation > 0`` guards and is
therefore correctly invisible at 0. Lifting one of those to 1 would make it
start tombstoning a key no consumer has ever held, in every full set, forever
(code review round 1, finding 1).

Drives the migration module's ``upgrade()`` under a real ``MigrationContext``
rather than re-typing its SQL — a copy of the statement in the test would pass
while the migration itself drifted.
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
    / "e3a71c40b9d2_backfill_announcement_generation_floor.py"
)

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]


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
    tables = "information.info_item_sources"
    async with test_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables}"))
        await conn.execute(text("DELETE FROM information.info_items"))
        await conn.execute(text("DELETE FROM information.info_sources"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables}"))
        await conn.execute(text("DELETE FROM information.info_items"))
        await conn.execute(text("DELETE FROM information.info_sources"))


async def _run_upgrade(test_engine) -> None:
    module = _load_migration()

    def _apply(sync_conn):
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            module.upgrade()

    async with test_engine.begin() as conn:
        await conn.run_sync(_apply)


async def _bind(session, item: InfoItem, *, specs: list) -> None:
    source = InfoSource(url=f"https://example.test/{item.name}", source_specs=specs)
    session.add(source)
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )


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
async def test_an_announceable_row_lifts_to_one_and_carries_a_stamp(test_engine, session_factory):
    """The target population: bound, specs present, never bumped.

    The stamp matters as much as the counter: ``_drift`` dates announcement lag
    from ``announced_at``, so a bumped generation with a NULL stamp would render
    as drift of unknown age.
    """
    async with session_factory() as s:
        item = InfoItem(name="legacy", announcement_generation=0)
        s.add(item)
        await s.flush()
        await _bind(s, item, specs=_SPECS)
        await s.commit()

    await _run_upgrade(test_engine)

    assert (await _generations(session_factory))["legacy"] == (1, True)


@pytest.mark.asyncio
async def test_an_already_announced_row_is_untouched(test_engine, session_factory):
    """The predicate is ``= 0``, not ``>= 0`` — a real generation must not advance."""
    async with session_factory() as s:
        item = InfoItem(name="announced", announcement_generation=7)
        s.add(item)
        await s.flush()
        await _bind(s, item, specs=_SPECS)
        await s.commit()

    await _run_upgrade(test_engine)

    assert (await _generations(session_factory))["announced"][0] == 7


@pytest.mark.asyncio
async def test_a_row_the_snapshot_cannot_publish_live_stays_at_zero(test_engine, session_factory):
    """The scope guard — these rows are *correctly* invisible at generation 0.

    Both revoked lists in ``_collect_full_set`` filter on
    ``announcement_generation > 0``, so an unbound row and a row bound to a
    spec-less source publish nothing at 0. Lifting either to 1 would start a
    tombstone for a key no consumer has ever held, republished every period,
    forever — and would falsify the snapshot module's stated rule that
    never-announced keys are absent from the full set.
    """
    async with session_factory() as s:
        unbound = InfoItem(name="unbound", announcement_generation=0)
        specless = InfoItem(name="specless", announcement_generation=0)
        s.add_all([unbound, specless])
        await s.flush()
        await _bind(s, specless, specs=[])
        await s.commit()

    await _run_upgrade(test_engine)

    after = await _generations(session_factory)
    assert after["unbound"] == (0, False)
    assert after["specless"] == (0, False)


@pytest.mark.asyncio
async def test_a_deactivated_binding_does_not_count_as_announceable(test_engine, session_factory):
    """``deactivated_at`` is the same liveness test the snapshot's join uses.

    A row whose only binding is deactivated is unbound as far as the registry is
    concerned, so it belongs with the untouched population above.
    """
    async with session_factory() as s:
        item = InfoItem(name="detached", announcement_generation=0)
        s.add(item)
        await s.flush()
        source = InfoSource(url="https://example.test/detached", source_specs=_SPECS)
        s.add(source)
        await s.flush()
        s.add(
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=source.info_source_id,
                deactivated_at=datetime.now(UTC),
            )
        )
        await s.commit()

    await _run_upgrade(test_engine)

    assert (await _generations(session_factory))["detached"] == (0, False)


@pytest.mark.asyncio
async def test_the_backfill_is_idempotent(test_engine, session_factory):
    """Re-running matches nothing — the second pass must not lift a real 1 to 2.

    An operator re-runs migrations; a backfill that advanced on every pass would
    manufacture announcements out of ``alembic upgrade head``.
    """
    async with session_factory() as s:
        item = InfoItem(name="legacy", announcement_generation=0)
        s.add(item)
        await s.flush()
        await _bind(s, item, specs=_SPECS)
        await s.commit()

    await _run_upgrade(test_engine)
    first = await _generations(session_factory)
    await _run_upgrade(test_engine)
    second = await _generations(session_factory)

    assert first["legacy"][0] == 1
    assert second["legacy"][0] == 1
