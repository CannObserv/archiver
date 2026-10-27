"""Watch lifecycle: archive and restore an InfoItem (archiver#361).

Archive is orthogonal to pause (D1): it sets ``archived_at`` and leaves
``watch_active`` alone, so the announced ``active`` is ``false`` while archived
and the item's own state again once restored. A call that changes nothing
writes and announces nothing; a real transition announces once, at a higher
generation, which is what Watcher's reconcile needs to re-arm the item.
"""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource
from src.core.models.domain import Domain
from src.core.services.domain_policy import update_domain
from src.core.services.info_item_lifecycle import archive_info_item, restore_info_item
from src.core.services.registry_announcement import INFO_REGISTRY_TOPIC, announce_info_item

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]


@pytest.fixture(autouse=True)
async def _sweep_outbox(test_engine, committed_rows):
    """A committed test item's outbox rows go even when the test fails first."""
    yield
    item_ids = [str(pk) for model, pk in committed_rows if model is InfoItem]
    if item_ids:
        async with test_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM information.changes_outbox"
                    " WHERE topic = :topic AND payload->>'info_item_id' = ANY(:ids)"
                ),
                {"topic": INFO_REGISTRY_TOPIC, "ids": item_ids},
            )


async def _item(session, *, watch_active: bool | None = True, bound: bool = True) -> InfoItem:
    item = InfoItem(name="lifecycle", watch_active=watch_active)
    session.add(item)
    await session.flush()
    if bound:
        source = InfoSource(url="https://lifecycle.example.test/x", source_specs=_SPECS)
        session.add(source)
        await session.flush()
        session.add(
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
        )
        await session.flush()
    return item


async def _announced(session, item: InfoItem) -> list[tuple[int, bool | None]]:
    """``(generation, active)`` for each of the item's announcements, in order."""
    rows = (
        await session.execute(
            select(ChangesOutboxRow.payload)
            .where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
            .order_by(ChangesOutboxRow.id)
        )
    ).scalars()
    return [
        (p["generation"], p["active"]) for p in rows if p["info_item_id"] == str(item.info_item_id)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("watch_active", [True, False, None])
async def test_archive_announces_inactive_once_and_keeps_the_pause_state(session, watch_active):
    item = await _item(session, watch_active=watch_active)

    archived = await archive_info_item(session, item.info_item_id)

    assert archived is item
    assert item.archived_at is not None
    assert item.watch_active is watch_active
    assert await _announced(session, item) == [(1, False)]


@pytest.mark.asyncio
async def test_a_second_archive_keeps_the_first_timestamp_and_emits_nothing(session):
    item = await _item(session)
    await archive_info_item(session, item.info_item_id)
    first = item.archived_at

    await archive_info_item(session, item.info_item_id)

    assert item.archived_at == first
    assert await _announced(session, item) == [(1, False)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("watch_active", "restored"), [(True, True), (False, False), (None, None)])
async def test_restore_returns_the_item_to_its_own_state_at_a_higher_generation(
    session, watch_active, restored
):
    """D1, and D2's pin: a paused item stays paused, an active one resumes, and
    the restore always outranks the archive - Watcher re-arms only on a higher
    generation (watcher#254 CR-23)."""
    item = await _item(session, watch_active=watch_active)
    await archive_info_item(session, item.info_item_id)

    await restore_info_item(session, item.info_item_id)

    assert item.archived_at is None
    assert await _announced(session, item) == [(1, False), (2, restored)]


@pytest.mark.asyncio
async def test_restoring_an_unarchived_item_writes_and_emits_nothing(session):
    item = await _item(session)

    assert await restore_info_item(session, item.info_item_id) is item

    assert item.archived_at is None
    assert await _announced(session, item) == []


@pytest.mark.asyncio
async def test_an_unannounceable_item_stores_the_state_and_emits_nothing(session):
    """#167: no consumer holds the key, so there is nothing to tell; the next
    binding announces with the archive already in place."""
    item = await _item(session, bound=False)

    await archive_info_item(session, item.info_item_id)

    assert item.archived_at is not None
    assert item.announcement_generation == 0
    assert await _announced(session, item) == []


@pytest.mark.asyncio
async def test_a_missing_item_is_none(session):
    item = await _item(session, bound=False)
    missing = item.info_item_id
    await session.delete(item)
    await session.flush()

    assert await archive_info_item(session, missing) is None
    assert await restore_info_item(session, missing) is None


@pytest.mark.asyncio
async def test_pause_on_an_archived_item_is_stored_and_the_wire_stays_inactive(session):
    """D3: intent is accepted while archived; the wire says ``false`` until restore."""
    item = await _item(session, watch_active=True)
    await archive_info_item(session, item.info_item_id)
    item.watch_active = False
    await session.flush()
    await announce_info_item(session, item.info_item_id)

    await restore_info_item(session, item.info_item_id)

    assert await _announced(session, item) == [(1, False), (2, False), (3, False)]


# --- Races (the #360 pair, with archive in place of a pause) -----------------


async def _until_waiting_on_a_lock(test_engine, pid: asyncio.Future, *, timeout=5.0) -> bool:
    """Proof that *this* backend is blocked on a lock, not merely unfinished."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    backend = await asyncio.wait_for(pid, timeout=timeout)
    async with test_engine.connect() as conn:
        while loop.time() < deadline:
            waiting = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE pid = :pid AND wait_event_type = 'Lock'"
                    ),
                    {"pid": backend},
                )
            ).scalar_one()
            await conn.rollback()  # end the snapshot, or every poll re-reads it
            if waiting:
                return True
            await asyncio.sleep(0.05)
    return False


async def _committed_item(factory, committed_rows, host: str, *, bound: bool) -> tuple:
    async with factory() as setup:
        domain = Domain(name=host)
        item = InfoItem(name=host, watch_active=True)
        source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
        setup.add_all([domain, item, source])
        await setup.flush()
        committed_rows += [
            (Domain, domain.id),
            (InfoSource, source.info_source_id),
            (InfoItem, item.info_item_id),
        ]
        if bound:
            binding = InfoItemSource(
                info_item_id=item.info_item_id, info_source_id=source.info_source_id
            )
            setup.add(binding)
            await setup.flush()
            committed_rows.append((InfoItemSource, binding.id))
        await setup.commit()
        return item, source


async def _archiving(factory, item_id, pid: asyncio.Future) -> None:
    async with factory() as s:
        pid.set_result((await s.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        await archive_info_item(s, item_id)
        await s.commit()


async def _rows(factory, committed_rows, item_id) -> list[tuple[int, bool | None]]:
    async with factory() as check:
        rows = (
            await check.execute(
                select(ChangesOutboxRow)
                .where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
                .order_by(ChangesOutboxRow.id)
            )
        ).scalars()
        mine = [r for r in rows if r.payload["info_item_id"] == str(item_id)]
    committed_rows += [(ChangesOutboxRow, r.id) for r in mine]
    return sorted((r.payload["generation"], r.payload["active"]) for r in mine)


@pytest.mark.asyncio
async def test_an_archive_racing_a_binding_announce_announces_last(test_engine, committed_rows):
    """The binding announce holds the item; the archive waits on it, then
    announces the final state above it - never a live ``true`` on top."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    item, source = await _committed_item(
        factory, committed_rows, "archive-bind.example.test", bound=False
    )

    pid = asyncio.get_running_loop().create_future()
    async with factory() as binder:
        binding = InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=source.info_source_id
        )
        binder.add(binding)
        await binder.flush()
        committed_rows.append((InfoItemSource, binding.id))
        await announce_info_item(binder, item.info_item_id)  # holds the item FOR UPDATE
        archiver = asyncio.create_task(_archiving(factory, item.info_item_id, pid))
        try:
            waited = await _until_waiting_on_a_lock(test_engine, pid)
            await binder.commit()
            await asyncio.wait_for(archiver, timeout=10)
        finally:
            archiver.cancel()
            await binder.rollback()
    assert waited, "the archive must wait on the binder's item lock"

    assert await _rows(factory, committed_rows, item.info_item_id) == [(1, True), (2, False)]


@pytest.mark.asyncio
async def test_a_host_restore_holding_the_item_is_outranked_by_the_archive(
    test_engine, committed_rows
):
    """A host flip locks its items first; an archive arriving meanwhile waits,
    then announces ``false`` above the flip's ``true``."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    host = "archive-flip.example.test"
    item, _source = await _committed_item(factory, committed_rows, host, bound=True)
    async with factory() as s:
        await update_domain(s, host, {"is_active": False}, create=False)
        await s.commit()

    pid = asyncio.get_running_loop().create_future()
    async with factory() as flipper:
        await update_domain(flipper, host, {"is_active": True}, create=False)  # holds the item
        archiver = asyncio.create_task(_archiving(factory, item.info_item_id, pid))
        try:
            waited = await _until_waiting_on_a_lock(test_engine, pid)
            await flipper.commit()
            await asyncio.wait_for(archiver, timeout=10)
        finally:
            archiver.cancel()
            await flipper.rollback()
    assert waited, "the archive must wait on the flip's item lock"

    assert await _rows(factory, committed_rows, item.info_item_id) == [
        (1, False),
        (2, True),
        (3, False),
    ]


@pytest.mark.asyncio
async def test_a_host_flip_waiting_on_an_archive_leaves_the_item_alone(test_engine, committed_rows):
    """The other order: the archive holds the item; the flip waits, then re-reads
    it under its own lock, finds it archived, and announces nothing for it."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    host = "flip-waits.example.test"
    item, _source = await _committed_item(factory, committed_rows, host, bound=True)

    pid = asyncio.get_running_loop().create_future()

    async def _flipping() -> None:
        async with factory() as s:
            pid.set_result((await s.execute(text("SELECT pg_backend_pid()"))).scalar_one())
            await update_domain(s, host, {"is_active": False}, create=False)
            await s.commit()

    async with factory() as archiving:
        await archive_info_item(archiving, item.info_item_id)  # holds the item
        flipper = asyncio.create_task(_flipping())
        try:
            waited = await _until_waiting_on_a_lock(test_engine, pid)
            await archiving.commit()
            await asyncio.wait_for(flipper, timeout=10)
        finally:
            flipper.cancel()
            await archiving.rollback()
    assert waited, "the flip must wait on the archive's item lock"

    assert await _rows(factory, committed_rows, item.info_item_id) == [(1, False)]
