"""Tests for the bind_info_source core tool."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource
from src.core.tools.bind_info_source import (
    ActiveBindingAlreadyExistsError,
    InfoItemNotFoundError,
    InfoSourceAlreadyBoundError,
    InfoSourceNotFoundError,
    bind_info_source,
)
from src.core.tools.rep_fields_gate import lock_info_item


def _spec(algorithm: str = "full_page") -> dict:
    doc: dict = {
        "schema_version": 1,
        "extraction": {"algorithm": algorithm},
        "fingerprint": {},
    }
    if algorithm != "full_page":
        doc["extraction"]["selector"] = "#x"
    return doc


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


@pytest.fixture
async def source(session):
    src = InfoSource(url="https://example.com/p", source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def other_source(session):
    src = InfoSource(url="https://example.com/q", source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


# --- happy path ---


@pytest.mark.asyncio
async def test_bind_creates_active_binding(session, item, source):
    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )
    assert binding.info_item_id == item.info_item_id
    assert binding.info_source_id == source.info_source_id
    assert binding.deactivated_at is None


@pytest.mark.asyncio
async def test_deactivated_binding_allows_new_active(session, item, source, other_source):
    old = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        deactivated_at=datetime.now(UTC),
    )
    session.add(old)
    await session.commit()
    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=other_source.info_source_id
    )
    assert binding.deactivated_at is None


@pytest.mark.asyncio
async def test_binding_a_previous_primary_starts_a_new_tenure(session, item, source):
    """It used to collide with the history row on the composite key: a 500 (archiver#389)."""
    old = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        deactivated_at=datetime.now(UTC),
    )
    session.add(old)
    await session.flush()
    first_tenure_end = old.deactivated_at

    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )

    assert binding.id != old.id
    assert binding.deactivated_at is None
    assert old.deactivated_at == first_tenure_end


# --- info_item_primary_changed: the tool emits, so no bind path can forget (archiver#390) ---


async def _primary_changed(session) -> list[dict]:
    payloads = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.changes")
        )
    ).scalars()
    return [p for p in payloads if p.get("event_type") == "info_item_primary_changed"]


@pytest.mark.asyncio
async def test_first_assignment_emits_once_with_no_old(session, item, source):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )

    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["info_item_id"] == str(item.info_item_id)
    assert events[0]["old_info_source_id"] is None
    assert events[0]["new_info_source_id"] == str(source.info_source_id)


@pytest.mark.asyncio
async def test_succession_emits_the_latest_closed_tenure_as_old(
    session, item, source, other_source
):
    """Two closed tenures: ``old`` is the one closed last, not the one opened first."""
    third = InfoSource(url="https://example.com/r", source_specs=[_spec()])
    session.add(third)
    await session.flush()
    session.add_all(
        [
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=source.info_source_id,
                deactivated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=other_source.info_source_id,
                deactivated_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        ]
    )
    await session.flush()

    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=third.info_source_id
    )

    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["old_info_source_id"] == str(other_source.info_source_id)
    assert events[0]["new_info_source_id"] == str(third.info_source_id)


@pytest.mark.asyncio
async def test_equal_close_times_break_the_tie_by_tenure_id(session, item, source, other_source):
    """Same ``deactivated_at``: the later tenure (the larger ULID ``id``) is ``old`` (CR 3)."""
    third = InfoSource(url="https://example.com/r", source_specs=[_spec()])
    session.add(third)
    await session.flush()
    closed = datetime(2026, 3, 1, tzinfo=UTC)
    earlier_id, later_id = sorted([ULID(), ULID()])
    # The earlier tenure goes in first, so heap order alone would pick it.
    for tenure_id, src in ((earlier_id, source), (later_id, other_source)):
        session.add(
            InfoItemSource(
                id=tenure_id,
                info_item_id=item.info_item_id,
                info_source_id=src.info_source_id,
                deactivated_at=closed,
            )
        )
        await session.flush()

    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=third.info_source_id
    )

    events = await _primary_changed(session)
    assert events[0]["old_info_source_id"] == str(other_source.info_source_id)


@pytest.mark.asyncio
async def test_a_refused_bind_emits_nothing(session, item, source, other_source):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )
    with pytest.raises(ActiveBindingAlreadyExistsError):
        await bind_info_source(
            session, info_item_id=item.info_item_id, info_source_id=other_source.info_source_id
        )
    with pytest.raises(InfoSourceNotFoundError):
        await bind_info_source(session, info_item_id=item.info_item_id, info_source_id=ULID())

    assert len(await _primary_changed(session)) == 1


# --- collision guard ---


@pytest.mark.asyncio
async def test_second_active_binding_rejected(session, item, source, other_source):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )
    with pytest.raises(ActiveBindingAlreadyExistsError) as exc_info:
        await bind_info_source(
            session, info_item_id=item.info_item_id, info_source_id=other_source.info_source_id
        )
    assert exc_info.value.existing_info_source_id == source.info_source_id


# --- existence ---


@pytest.mark.asyncio
async def test_unknown_info_item_rejected(session, source):
    with pytest.raises(InfoItemNotFoundError):
        await bind_info_source(session, info_item_id=ULID(), info_source_id=source.info_source_id)


@pytest.mark.asyncio
async def test_unknown_info_source_rejected(session, item):
    with pytest.raises(InfoSourceNotFoundError):
        await bind_info_source(session, info_item_id=item.info_item_id, info_source_id=ULID())


# --- concurrency: the InfoItem row serializes a bind against a swap ---


@pytest.mark.asyncio
async def test_a_bind_waits_for_a_swap_and_then_sees_its_primary(test_engine, committed_rows):
    """``swap_primary_source`` holds the item lock while it binds. Without the
    same lock here, both see no primary, and the later insert collides on
    ``uq_info_item_sources_active``: a 500 instead of the 409 (archiver#45)."""
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with make_session() as setup:
        item = InfoItem(name="race bind")
        b, c = (
            InfoSource(url=f"https://example.com/race-bind-{n}", source_specs=[_spec()])
            for n in "bc"
        )
        setup.add_all([item, b, c])
        await setup.commit()
        committed_rows += [(InfoSource, b.info_source_id), (InfoSource, c.info_source_id)]
        committed_rows.append((InfoItem, item.info_item_id))

    async with make_session() as swapper, make_session() as binder:
        await lock_info_item(swapper, item.info_item_id)
        swapper.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=b.info_source_id))
        await swapper.flush()

        task = asyncio.create_task(
            bind_info_source(
                binder, info_item_id=item.info_item_id, info_source_id=c.info_source_id
            )
        )
        done, _ = await asyncio.wait({task}, timeout=1.0)
        assert not done, "bind proceeded while a swap held the InfoItem row"

        await swapper.commit()
        with pytest.raises(ActiveBindingAlreadyExistsError):
            await asyncio.wait_for(task, timeout=10.0)
        await binder.rollback()


# --- require_unbound_source: registration's Case B reuse (archiver#51) ---


@pytest.fixture
async def other_item(session):
    obj = InfoItem(name="other")
    session.add(obj)
    await session.flush()
    return obj


@pytest.mark.asyncio
async def test_require_unbound_binds_an_unbound_source(session, item, source):
    binding = await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        require_unbound_source=True,
    )
    assert binding.info_source_id == source.info_source_id
    assert len(await _primary_changed(session)) == 1


@pytest.mark.asyncio
async def test_require_unbound_refuses_a_source_another_item_holds(
    session, item, other_item, source
):
    await bind_info_source(
        session, info_item_id=other_item.info_item_id, info_source_id=source.info_source_id
    )
    with pytest.raises(InfoSourceAlreadyBoundError) as exc_info:
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=source.info_source_id,
            require_unbound_source=True,
        )
    assert exc_info.value.info_item_ids == [other_item.info_item_id]
    # The refusal wrote nothing: one binding, one event, both other_item's.
    assert len(await _primary_changed(session)) == 1


@pytest.mark.asyncio
async def test_a_closed_tenure_elsewhere_does_not_count_as_bound(session, item, other_item, source):
    """Unbound means no *active* binding: the source's history is what reuse keeps."""
    old = await bind_info_source(
        session, info_item_id=other_item.info_item_id, info_source_id=source.info_source_id
    )
    old.deactivated_at = datetime.now(UTC)
    await session.flush()

    binding = await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        require_unbound_source=True,
    )
    assert binding.deactivated_at is None


@pytest.mark.asyncio
async def test_without_the_flag_a_bound_source_can_still_be_shared(
    session, item, other_item, source
):
    """Every other bind path keeps today's behaviour: the model allows sharing (Case A)."""
    await bind_info_source(
        session, info_item_id=other_item.info_item_id, info_source_id=source.info_source_id
    )
    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )
    assert binding.info_source_id == source.info_source_id


# --- concurrency: the InfoSource row serializes two binds of one source ---


async def _committed_pair(make_session, committed_rows, label: str):
    async with make_session() as setup:
        a, b = InfoItem(name=f"{label} a"), InfoItem(name=f"{label} b")
        src = InfoSource(url=f"https://example.com/{label}", source_specs=[_spec()])
        setup.add_all([a, b, src])
        await setup.commit()
        committed_rows.append((InfoSource, src.info_source_id))
        committed_rows += [(InfoItem, a.info_item_id), (InfoItem, b.info_item_id)]
        return a.info_item_id, b.info_item_id, src.info_source_id


async def _track_bind_writes(make_session, committed_rows, source_id) -> None:
    bindings = select(InfoItemSource).where(InfoItemSource.info_source_id == source_id)
    events = select(ChangesOutboxRow).where(ChangesOutboxRow.topic == "info.changes")
    async with make_session() as s:
        for binding in (await s.execute(bindings)).scalars():
            committed_rows.append((InfoItemSource, binding.id))
        for row in (await s.execute(events)).scalars():
            if row.payload.get("new_info_source_id") == str(source_id):
                committed_rows.append((ChangesOutboxRow, row.id))


@pytest.mark.asyncio
async def test_two_unbound_binds_of_one_source_serialize(test_engine, committed_rows):
    """Case B's item is new, so the item lock serializes nothing. Without a lock
    on the source, two registrations both see it unbound and both bind it."""
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)
    a, b, source_id = await _committed_pair(make_session, committed_rows, "race-unbound")

    try:
        async with make_session() as first, make_session() as second:
            await bind_info_source(
                first, info_item_id=a, info_source_id=source_id, require_unbound_source=True
            )
            task = asyncio.create_task(
                bind_info_source(
                    second, info_item_id=b, info_source_id=source_id, require_unbound_source=True
                )
            )
            done, _ = await asyncio.wait({task}, timeout=1.0)
            assert not done, "a second bind proceeded while the first held the InfoSource row"

            await first.commit()
            with pytest.raises(InfoSourceAlreadyBoundError):
                await asyncio.wait_for(task, timeout=10.0)
            await second.rollback()
    finally:
        await _track_bind_writes(make_session, committed_rows, source_id)


@pytest.mark.asyncio
async def test_the_source_lock_does_not_stall_revision_ingest(test_engine, committed_rows):
    """A ``source_revisions`` insert takes FOR KEY SHARE on its source through the
    FK; the bind's lock must not conflict with it (FOR NO KEY UPDATE, not FOR UPDATE)."""
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)
    a, _b, source_id = await _committed_pair(make_session, committed_rows, "race-ingest")

    async with make_session() as binder, make_session() as ingest:
        await bind_info_source(binder, info_item_id=a, info_source_id=source_id)
        key_share = ingest.execute(
            select(InfoSource.info_source_id)
            .where(InfoSource.info_source_id == source_id)
            .with_for_update(read=True, key_share=True)
        )
        await asyncio.wait_for(key_share, timeout=2.0)
        await ingest.rollback()
        await binder.rollback()
