"""Domain writes that can suspend or resume a host (archiver#360).

A suspension flip announces every item whose *resolved* ``active`` changes, in
the write's transaction, through the policy path (no tombstones). A write that
flips nothing emits nothing (the #167 rule).
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource
from src.core.models.domain import Domain
from src.core.services import domain_policy
from src.core.services.domain_policy import update_domain
from src.core.services.registry_announcement import INFO_REGISTRY_TOPIC, announce_info_item

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]
HOST = "policy.example.test"


@pytest.fixture(autouse=True)
async def _sweep_outbox(test_engine, committed_rows):
    """CR 16: a committed test item's outbox rows go even when the test fails
    before tracking them. Torn down before ``committed_rows``, which it wraps."""
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


async def _until_waiting_on_a_lock(
    test_engine, pid: asyncio.Future, *, timeout: float = 5.0
) -> bool:
    """CR 17/25: proof that *this* backend is blocked on a lock, not merely
    unfinished - and not some other backend in the test database."""
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
            # pg_stat_activity is snapshotted once per transaction: end it, or
            # every later poll re-reads the first, pre-wait view.
            await conn.rollback()
            if waiting:
                return True
            await asyncio.sleep(0.05)
    return False


async def _deactivating(factory, host: str, pid: asyncio.Future) -> None:
    """Deactivate ``host`` in a session of its own, publishing its backend pid."""
    async with factory() as s:
        pid.set_result((await s.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        await update_domain(s, host, {"is_active": False}, create=False)
        await s.commit()


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

    pid = asyncio.get_running_loop().create_future()
    binding = InfoItemSource(info_item_id=item_id, info_source_id=source.info_source_id)
    # Whatever fails, release both transactions: an open one holds row locks
    # that would hang teardown and every later test.
    async with factory() as binder:
        binder.add(binding)
        await binder.flush()
        committed_rows.append((InfoItemSource, binding.id))
        await announce_info_item(binder, item_id)  # holds the Domain row FOR KEY SHARE
        writer = asyncio.create_task(_deactivating(factory, host, pid))
        try:
            waited = await _until_waiting_on_a_lock(test_engine, pid)
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


@pytest.mark.asyncio
async def test_a_newcomer_held_by_an_announce_does_not_deadlock_the_write(
    test_engine, committed_rows, monkeypatch
):
    """CR 2 (archiver#360): newcomers are locked before the Domain row, never after.

    Item N is bound to the host after the write locked the host's items. An
    announce on N holds N and then wants the row ``FOR KEY SHARE``. If the write took
    the row and then waited on N, Postgres would abort one of them as a deadlock.
    The write releases the row (savepoint), locks N in item order, and retries,
    so both commit and N ends up announced inactive.
    """
    host = "newcomer.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as setup:
        domain = Domain(name=host)
        old = InfoItem(name="old", watch_active=True)
        new = InfoItem(name="new", watch_active=True)
        source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
        setup.add_all([domain, old, new, source])
        await setup.flush()
        old_binding = InfoItemSource(
            info_item_id=old.info_item_id, info_source_id=source.info_source_id
        )
        setup.add(old_binding)
        await setup.commit()
        committed_rows += [
            (Domain, domain.id),
            (InfoSource, source.info_source_id),
            (InfoItem, old.info_item_id),
            (InfoItem, new.info_item_id),
            (InfoItemSource, old_binding.id),
        ]
        new_id = new.info_item_id

    paused, release = asyncio.Event(), asyncio.Event()
    real_host_items = domain_policy._host_items
    calls = 0

    async def _pausing_host_items(session, name, *, lock):
        nonlocal calls
        result = await real_host_items(session, name, lock=lock)
        calls += 1
        if calls == 1:  # after the first item lock, before the row lock
            paused.set()
            await release.wait()
        return result

    monkeypatch.setattr(domain_policy, "_host_items", _pausing_host_items)

    pid = asyncio.get_running_loop().create_future()
    writer = asyncio.create_task(_deactivating(factory, host, pid))
    async with factory() as binder, factory() as announcer:
        try:
            await asyncio.wait_for(paused.wait(), timeout=5)
            binding = InfoItemSource(info_item_id=new_id, info_source_id=source.info_source_id)
            binder.add(binding)
            await binder.commit()
            committed_rows.append((InfoItemSource, binding.id))

            # The announce holds N first, as _announce_many does.
            await announcer.execute(
                select(InfoItem).where(InfoItem.info_item_id == new_id).with_for_update()
            )
            release.set()
            # The write reaches N and blocks on it; only then may the announce
            # ask for the row, which is what would close the old cycle.
            assert await _until_waiting_on_a_lock(test_engine, pid)
            await announce_info_item(announcer, new_id)
            await announcer.commit()
            await asyncio.wait_for(writer, timeout=10)
        finally:
            release.set()
            writer.cancel()
            await announcer.rollback()

    async with factory() as check:
        rows = (
            await check.execute(
                select(ChangesOutboxRow).where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
            )
        ).scalars()
        mine = [r for r in rows if r.payload["info_item_id"] == str(new_id)]
        committed_rows += [(ChangesOutboxRow, r.id) for r in mine]
        old_rows = [
            r
            for r in (
                await check.execute(
                    select(ChangesOutboxRow).where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
                )
            ).scalars()
            if r.payload["info_item_id"] == str(old.info_item_id)
        ]
        committed_rows += [(ChangesOutboxRow, r.id) for r in old_rows]
    last = max(mine, key=lambda r: r.payload["generation"])
    assert last.payload["active"] is False


@pytest.mark.asyncio
async def test_a_plain_domain_update_does_not_block_an_announce(test_engine, committed_rows):
    """CR 7: announces take the row FOR KEY SHARE, which only ``update_domain``'s
    FOR UPDATE conflicts with - a notes edit in flight must not stall them."""
    host = "keyshare.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as setup:
        domain = Domain(name=host)
        item = InfoItem(name="keyshare", watch_active=True)
        source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
        setup.add_all([domain, item, source])
        await setup.flush()
        binding = InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=source.info_source_id
        )
        setup.add(binding)
        await setup.commit()
        committed_rows += [
            (Domain, domain.id),
            (InfoSource, source.info_source_id),
            (InfoItem, item.info_item_id),
            (InfoItemSource, binding.id),
        ]

    async with factory() as editor, factory() as announcer:
        try:
            row = (await editor.execute(select(Domain).where(Domain.name == host))).scalar_one()
            row.notes = "in flight"
            await editor.flush()  # holds the row FOR NO KEY UPDATE, uncommitted

            await asyncio.wait_for(announce_info_item(announcer, item.info_item_id), timeout=3)
            rows = (
                await announcer.execute(
                    select(ChangesOutboxRow).where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
                )
            ).scalars()
            mine = [r for r in rows if r.payload["info_item_id"] == str(item.info_item_id)]
            await announcer.commit()
            committed_rows += [(ChangesOutboxRow, r.id) for r in mine]
        finally:
            await announcer.rollback()
            await editor.rollback()
    assert len(mine) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"notes": "n"},
        {"min_interval_seconds": 2.0},
        {"default_watch_spec": {"schema_version": 1, "interval": "1d"}},
    ],
)
async def test_a_write_that_cannot_flip_takes_no_item_locks(test_engine, committed_rows, changes):
    """CR 13: only is_active/archived_at can flip suspension; nothing else may
    block item writes across the host."""
    host = "nolock.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as setup:
        domain = Domain(name=host)
        item = InfoItem(name="nolock", watch_active=True)
        source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
        setup.add_all([domain, item, source])
        await setup.flush()
        binding = InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=source.info_source_id
        )
        setup.add(binding)
        await setup.commit()
        committed_rows += [
            (Domain, domain.id),
            (InfoSource, source.info_source_id),
            (InfoItem, item.info_item_id),
            (InfoItemSource, binding.id),
        ]

    async with factory() as holder, factory() as writer:
        try:
            await holder.execute(
                select(InfoItem).where(InfoItem.info_item_id == item.info_item_id).with_for_update()
            )
            await asyncio.wait_for(update_domain(writer, host, changes, create=False), timeout=3)
            await writer.commit()
        finally:
            await writer.rollback()
            await holder.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [{"notes": "n"}, {"min_interval_seconds": 3.0}, {"default_watch_spec": None}],
)
async def test_a_non_flipping_update_domain_does_not_block_an_announce(
    test_engine, committed_rows, changes
):
    """CR 24: the fast path takes FOR NO KEY UPDATE, which an announce's KEY SHARE
    does not wait on - only a write that can flip holds the row FOR UPDATE."""
    host = "fastpath.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as setup:
        domain = Domain(name=host)
        item = InfoItem(name="fastpath", watch_active=True)
        source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
        setup.add_all([domain, item, source])
        await setup.flush()
        binding = InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=source.info_source_id
        )
        setup.add(binding)
        await setup.commit()
        committed_rows += [
            (Domain, domain.id),
            (InfoSource, source.info_source_id),
            (InfoItem, item.info_item_id),
            (InfoItemSource, binding.id),
        ]

    async with factory() as writer, factory() as announcer:
        try:
            await update_domain(writer, host, changes, create=False)  # uncommitted
            await asyncio.wait_for(announce_info_item(announcer, item.info_item_id), timeout=3)
            await announcer.commit()
        finally:
            await announcer.rollback()
            await writer.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"is_active": False}, {"notes": "n"}])
async def test_a_create_racing_a_delete_returns_none(
    test_engine, committed_rows, monkeypatch, changes
):
    """CR 26: the row is deleted and committed between the upsert's insert (a no-op,
    the row existed) and its lock. The write sees no row and says so - the API
    turns that into a 409 (CR 15) - rather than inventing one."""
    host = "deleted-mid-upsert.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as setup:
        domain = Domain(name=host)
        setup.add(domain)
        await setup.commit()
        committed_rows.append((Domain, domain.id))

    real_insert = domain_policy._insert_if_absent

    async def _insert_then_lose_the_row(session, name):
        await real_insert(session, name)
        async with test_engine.begin() as other:
            await other.execute(
                text("DELETE FROM information.domains WHERE name = :n"), {"n": name}
            )

    monkeypatch.setattr(domain_policy, "_insert_if_absent", _insert_then_lose_the_row)
    async with factory() as s:
        assert await update_domain(s, host, changes, create=True) is None
        await s.rollback()
