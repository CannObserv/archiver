"""Domain writes that can suspend or resume a host (archiver#360).

A suspension flip announces every item whose *resolved* ``active`` changes, in
the write's transaction, through the policy path (no tombstones). A write that
flips nothing emits nothing (the #167 rule).
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource
from src.core.models.domain import Domain
from src.core.services.domain_policy import update_domain
from src.core.services.registry_announcement import INFO_REGISTRY_TOPIC, announce_info_item

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]
HOST = "policy.example.test"


async def _item_on(session, host: str = HOST, *, watch_active: bool | None = True) -> InfoItem:
    item = InfoItem(name=f"on {host}", watch_active=watch_active, announcement_generation=1)
    source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
    session.add_all([item, source])
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    await session.flush()
    return item


async def _announced(session) -> dict[str, list]:
    rows = (
        await session.execute(
            select(ChangesOutboxRow.payload)
            .where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
            .order_by(ChangesOutboxRow.id)
        )
    ).scalars()
    out: dict[str, list] = {}
    for payload in rows:
        out.setdefault(payload["info_item_id"], []).append(payload["active"])
    return out


@pytest.mark.asyncio
async def test_deactivating_announces_inactive_for_every_item_whose_state_changes(session):
    session.add(Domain(name=HOST))
    on = await _item_on(session, watch_active=True)
    unknown = await _item_on(session, watch_active=None)
    paused = await _item_on(session, watch_active=False)
    elsewhere = await _item_on(session, "other.example.test")

    await update_domain(session, HOST, {"is_active": False}, create=False)

    announced = await _announced(session)
    assert announced == {str(on.info_item_id): [False], str(unknown.info_item_id): [False]}
    assert str(paused.info_item_id) not in announced  # false either way
    assert str(elsewhere.info_item_id) not in announced


@pytest.mark.asyncio
async def test_reactivating_returns_each_item_to_its_own_state(session):
    session.add(Domain(name=HOST, is_active=False))
    on = await _item_on(session, watch_active=True)
    unknown = await _item_on(session, watch_active=None)

    await update_domain(session, HOST, {"is_active": True}, create=False)

    assert await _announced(session) == {
        str(on.info_item_id): [True],
        str(unknown.info_item_id): [None],
    }


@pytest.mark.asyncio
async def test_archive_and_restore_flip_suspension_too(session):
    session.add(Domain(name=HOST))
    item = await _item_on(session)

    await update_domain(session, HOST, {"archived_at": datetime.now(UTC)}, create=False)
    await update_domain(session, HOST, {"archived_at": None}, create=False)

    assert await _announced(session) == {str(item.info_item_id): [False, True]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"archived_at": datetime(2026, 10, 24, tzinfo=UTC)},  # already inactive
        {"notes": "n"},
        {"min_interval_seconds": 5.0},
        {"default_watch_spec": {"schema_version": 1, "interval": "6h"}},
        {"is_active": False},  # already inactive: no flip
    ],
)
async def test_a_write_that_flips_nothing_emits_nothing(session, changes):
    session.add(Domain(name=HOST, is_active=False))
    await _item_on(session)

    await update_domain(session, HOST, changes, create=False)

    assert await _announced(session) == {}


@pytest.mark.asyncio
async def test_an_unannounceable_item_on_the_host_is_not_announced(session):
    session.add(Domain(name=HOST))
    item = InfoItem(name="specless", watch_active=True, announcement_generation=1)
    source = InfoSource(url=f"https://{HOST}/empty", source_specs=[], domain_name=HOST)
    session.add_all([item, source])
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    await session.flush()

    await update_domain(session, HOST, {"is_active": False}, create=False)

    assert await _announced(session) == {}


@pytest.mark.asyncio
async def test_creating_an_inactive_row_for_a_host_sources_already_name_fans_out(session):
    """``domain_name`` has no FK: a row-less host is active, so this create is a flip."""
    item = await _item_on(session)

    domain = await update_domain(session, HOST, {"is_active": False}, create=True)

    assert domain is not None and domain.is_active is False
    assert await _announced(session) == {str(item.info_item_id): [False]}


@pytest.mark.asyncio
async def test_a_missing_row_without_create_is_none_and_emits_nothing(session):
    await _item_on(session)

    assert await update_domain(session, HOST, {"is_active": False}, create=False) is None
    assert await _announced(session) == {}


@pytest.mark.asyncio
async def test_unknown_columns_are_refused(session):
    session.add(Domain(name=HOST))
    with pytest.raises(ValueError, match="name"):
        await update_domain(session, HOST, {"name": "evil"}, create=False)


@pytest.mark.asyncio
async def test_a_binding_committed_while_the_write_waits_is_announced_inactive(
    test_engine, committed_rows
):
    """The race the lock order exists for (archiver#360).

    A binding transaction announces its item under a share lock on the host's
    Domain row. A deactivation that arrives meanwhile has already chosen its
    item set; it waits on that share lock, then re-reads the host's items and
    announces the newcomer too. Without the share lock it would not wait, and
    without the re-read it would miss the item: either way the item would stay
    announced active on a suspended host at the higher generation.
    """
    host = "race.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as setup:
        domain = Domain(name=host)
        item = InfoItem(name="race", watch_active=True)
        source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
        setup.add_all([domain, item, source])
        await setup.commit()
        committed_rows += [
            (Domain, domain.id),
            (InfoSource, source.info_source_id),
            (InfoItem, item.info_item_id),
        ]
        item_id = item.info_item_id

    async def _deactivate() -> None:
        async with factory() as s:
            await update_domain(s, host, {"is_active": False}, create=False)
            await s.commit()

    binding = InfoItemSource(info_item_id=item_id, info_source_id=source.info_source_id)
    # Whatever fails, release both transactions: an open one holds row locks
    # that would hang teardown and every later test.
    async with factory() as binder:
        binder.add(binding)
        await binder.flush()
        committed_rows.append((InfoItemSource, binding.id))
        await announce_info_item(binder, item_id)  # holds the Domain row FOR SHARE
        writer = asyncio.create_task(_deactivate())
        try:
            await asyncio.sleep(0.3)
            waited = not writer.done()
            await binder.commit()
            await asyncio.wait_for(writer, timeout=10)
        finally:
            writer.cancel()
            await binder.rollback()
    assert waited, "the domain write must wait on the binder's share lock"

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
        last = max(mine, key=lambda r: r.payload["generation"])
    assert [r.payload["active"] for r in mine] == [True, False]
    assert last.payload["active"] is False
