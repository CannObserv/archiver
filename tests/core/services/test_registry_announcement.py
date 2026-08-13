"""The ``info.registry`` announcement service (archiver#141).

One function behind every emit site. Sixteen hand-built payloads across the API
and dashboard would drift; one builder cannot. The service owns the atomic
generation bump, the joined read of announced state, and the
``changes_outbox`` row — callers get one line, inside their own transaction.

The live/revoked/skip rule:

- active primary binding present → **live** announcement
- no active binding, previously announced → **revoked** (the item is
  unannounceable, and skipping would leave the consumer fetching the old URL
  forever — the exact drift bug this channel removes)
- no active binding, never announced → **skip** (the consumer has never heard
  of the key; a tombstone for it would only grow every consumer's tombstone
  table)
"""

import asyncio
from datetime import UTC, datetime

import pytest
from co_core.pure.adapters.bus.envelope import payload_from_dict, to_wire
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import (
    ChangesOutboxRow,
    InfoItem,
    InfoItemSource,
    InfoSource,
    RevokedInfoItem,
)
from src.core.services.registry_announcement import (
    INFO_REGISTRY_TOPIC,
    announce_for_info_source,
    announce_info_item,
    announce_info_item_revoked,
)

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]


async def _make_item(session, *, name: str = "Item", bound: bool = True) -> InfoItem:
    item = InfoItem(name=name)
    session.add(item)
    await session.flush()
    if bound:
        source = InfoSource(url="https://example.test/doc", source_specs=_SPECS)
        session.add(source)
        await session.flush()
        session.add(
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
        )
        await session.flush()
    return item


async def _outbox_rows(session) -> list[ChangesOutboxRow]:
    result = await session.execute(
        select(ChangesOutboxRow).where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
    )
    return list(result.scalars())


@pytest.mark.asyncio
async def test_live_announcement_carries_the_joined_state(session):
    item = await _make_item(session)

    await announce_info_item(session, item.info_item_id)

    (row,) = await _outbox_rows(session)
    payload = row.payload
    assert payload["event_type"] == "registry_announcement"
    assert payload["info_item_id"] == str(item.info_item_id)
    assert payload["generation"] == 1
    assert payload["url"] == "https://example.test/doc"
    assert payload["source_specs"] == _SPECS
    assert payload["watch_spec"] == {"schema_version": 1}
    assert payload["active"] is None  # column NULL = the registry has no opinion yet
    assert payload["revoked"] is False


@pytest.mark.asyncio
async def test_payload_round_trips_the_co_core_contract(session):
    """The outbox build phase dead-letters an unvalidatable payload on the FIRST
    attempt — so what the service writes must be exactly what co-core accepts."""
    item = await _make_item(session)

    await announce_info_item(session, item.info_item_id)

    (row,) = await _outbox_rows(session)
    wire = to_wire(payload_from_dict(row.payload))
    assert wire["key"].startswith(f"{item.info_item_id}:")


@pytest.mark.asyncio
async def test_generation_increments_per_announcement(session):
    item = await _make_item(session)

    await announce_info_item(session, item.info_item_id)
    await announce_info_item(session, item.info_item_id)

    rows = await _outbox_rows(session)
    assert sorted(r.payload["generation"] for r in rows) == [1, 2]


@pytest.mark.asyncio
async def test_watch_state_is_projected_from_the_columns(session):
    item = await _make_item(session)
    item.watch_spec = {"schema_version": 1, "interval": "6h"}
    item.watch_active = False
    await session.flush()

    await announce_info_item(session, item.info_item_id)

    (row,) = await _outbox_rows(session)
    assert row.payload["watch_spec"] == {"schema_version": 1, "interval": "6h"}
    assert row.payload["active"] is False


@pytest.mark.asyncio
async def test_never_announced_sourceless_item_emits_nothing(session):
    """A bare POST /info-items has no announced state — the key does not exist
    for any consumer, so there is nothing to announce and nothing to revoke."""
    item = await _make_item(session, bound=False)

    await announce_info_item(session, item.info_item_id)

    assert await _outbox_rows(session) == []


@pytest.mark.asyncio
async def test_previously_announced_item_losing_its_binding_emits_revoked(session):
    """Binding deactivation without a replacement announces revoked. Skipping
    would leave the consumer fetching the old URL forever; a later re-binding
    announces live at a higher generation and the consumer resurrects the key."""
    item = await _make_item(session)
    await announce_info_item(session, item.info_item_id)  # gen 1, live

    binding = (
        await session.execute(
            select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
        )
    ).scalar_one()
    binding.deactivated_at = datetime.now(UTC)
    await session.flush()

    await announce_info_item(session, item.info_item_id)

    rows = sorted(await _outbox_rows(session), key=lambda r: r.payload["generation"])
    assert rows[1].payload["revoked"] is True
    assert rows[1].payload["generation"] == 2
    # Tombstones are minimal — no hydrated state (cannobserv#324's ruling).
    assert rows[1].payload.get("url") is None
    assert rows[1].payload.get("source_specs") is None
    # And it still round-trips the contract.
    payload_from_dict(rows[1].payload)


@pytest.mark.asyncio
async def test_missing_item_is_a_silent_no_op(session):
    await announce_info_item(session, ULID())
    assert await _outbox_rows(session) == []


@pytest.mark.asyncio
async def test_fan_out_announces_every_item_actively_bound_to_the_source(session):
    """info_item_sources has no uniqueness on info_source_id — one InfoSource can
    be the active primary for several InfoItems. A spec edit is one mutation and
    N announcements, each with its own item's bumped generation."""
    source = InfoSource(url="https://example.test/shared", source_specs=_SPECS)
    session.add(source)
    await session.flush()

    items = []
    for name in ("a", "b"):
        item = InfoItem(name=name)
        session.add(item)
        await session.flush()
        session.add(
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
        )
        items.append(item)
    # A deactivated binding to the same source must NOT announce.
    stale_item = InfoItem(name="stale")
    session.add(stale_item)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=stale_item.info_item_id,
            info_source_id=source.info_source_id,
            deactivated_at=datetime.now(UTC),
        )
    )
    await session.flush()

    count = await announce_for_info_source(session, source.info_source_id)

    assert count == 2
    rows = await _outbox_rows(session)
    announced = {r.payload["info_item_id"] for r in rows}
    assert announced == {str(i.info_item_id) for i in items}
    assert all(r.payload["generation"] == 1 for r in rows)


@pytest.mark.asyncio
async def test_rollback_rolls_back_announcement_and_generation(session):
    """The whole point of the outbox: the announcement shares the mutation's
    transaction, so a rolled-back mutation leaves no orphaned announcement and
    no burned generation."""
    item = await _make_item(session)
    # session.rollback() below expires every instance regardless of
    # expire_on_commit, so reading item.info_item_id afterwards would lazy-load
    # in a sync context (MissingGreenlet). Capture it while it is loaded.
    item_id = item.info_item_id
    await announce_info_item(session, item_id)
    await session.commit()

    await announce_info_item(session, item_id)  # would be gen 2
    assert len(await _outbox_rows(session)) == 2
    await session.rollback()

    assert len(await _outbox_rows(session)) == 1
    gen = (
        await session.execute(
            select(InfoItem.announcement_generation).where(InfoItem.info_item_id == item_id)
        )
    ).scalar_one()
    assert gen == 1


@pytest.mark.asyncio
async def test_revoked_flow_records_the_tombstone_and_emits(session):
    """The DELETE route's flow: bump, record RevokedInfoItem, emit — all before
    the row itself is deleted, all in the deletion's transaction. The table is
    what the snapshot's full-set tombstone republish reads after the item row
    is gone."""
    item = await _make_item(session)
    await announce_info_item(session, item.info_item_id)  # gen 1

    await announce_info_item_revoked(session, item)
    await session.delete(item)
    await session.flush()

    revoked = (
        await session.execute(
            select(RevokedInfoItem).where(RevokedInfoItem.info_item_id == item.info_item_id)
        )
    ).scalar_one()
    assert revoked.generation == 2

    rows = sorted(await _outbox_rows(session), key=lambda r: r.payload["generation"])
    assert rows[1].payload["revoked"] is True
    assert rows[1].payload["generation"] == 2
    payload_from_dict(rows[1].payload)


@pytest.mark.asyncio
async def test_revoked_flow_on_a_never_announced_item_still_tombstones(session):
    """Deletion differs from unbinding: the row is about to be GONE, so there is
    no later mutation that could ever announce this key. Emitting even for a
    never-announced item costs one message; skipping risks a consumer that
    learned the key out of band keeping it forever."""
    item = await _make_item(session, bound=False)

    await announce_info_item_revoked(session, item)

    (row,) = await _outbox_rows(session)
    assert row.payload["revoked"] is True
    assert row.payload["generation"] == 1


@pytest.mark.asyncio
async def test_concurrent_bumps_yield_distinct_generations(test_engine, committed_rows):
    """The bump is an atomic ``UPDATE … RETURNING``, never read-modify-write.

    Two overlapping transactions announcing one item must produce generations
    N+1 and N+2 — the read-modify-write implementation both read N, both write
    N+1, and every consumer discards the second announcement as a duplicate.
    Real connections and real commits: row-lock behaviour is only observable
    across independent transactions (hence ``committed_rows``, not the
    SAVEPOINT ``session`` fixture).
    """
    factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async with factory() as setup:
        item = InfoItem(name="concurrent")
        source = InfoSource(url="https://example.test/concurrent", source_specs=_SPECS)
        setup.add_all([item, source])
        await setup.flush()
        setup.add(
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
        )
        await setup.commit()
        item_id = item.info_item_id
        committed_rows.append((InfoItemSource, (item_id, source.info_source_id)))
        committed_rows.append((InfoSource, source.info_source_id))
        committed_rows.append((InfoItem, item_id))

    generations: list[int] = []

    async def _announce_and_commit() -> None:
        async with factory() as s:
            await announce_info_item(s, item_id)
            await s.commit()

    await asyncio.gather(_announce_and_commit(), _announce_and_commit())

    async with factory() as check:
        payloads = (
            (
                await check.execute(
                    select(ChangesOutboxRow).where(
                        ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC,
                    )
                )
            )
            .scalars()
            .all()
        )
        mine = [r for r in payloads if r.payload["info_item_id"] == str(item_id)]
        generations = sorted(r.payload["generation"] for r in mine)
        for r in mine:
            committed_rows.append((ChangesOutboxRow, r.id))

    assert generations == [1, 2]
