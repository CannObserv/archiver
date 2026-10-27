"""Temporal-profile writes and the daily boundary (archiver#365).

A profile write and the boundary job are the only places a profile's result is
computed (D1); each locks the item first, stores the result, and announces only
when it moved. Post-actions fire at the boundary whatever the item's pause or
host state (D4), once (``fired_at``), and the item announces once with its
final state.
"""

import asyncio
import logging
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import (
    ChangesOutboxRow,
    Domain,
    InfoItem,
    InfoItemSource,
    InfoSource,
    TemporalProfile,
)
from src.core.services.domain_policy import update_domain
from src.core.services.registry_announcement import INFO_REGISTRY_TOPIC
from src.core.services.temporal_profiles import (
    BoundaryOutcome,
    ProfileInvalid,
    delete_temporal_profile,
    evaluate_at_boundary,
    put_temporal_profile,
    run_boundary,
)

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]
REF = date(2026, 4, 15)
RULES_30_7 = [{"days_before": 30, "interval": "6h"}, {"days_before": 7, "interval": "1h"}]


def _event(**kw) -> dict:
    return {
        "profile_type": "event",
        "reference_date": REF,
        "date_range_start": None,
        "date_range_end": None,
        "rules": RULES_30_7,
        "post_action": "reduce_frequency",
        "is_active": True,
    } | kw


async def _item(
    session,
    *,
    host: str = "profiles.example.test",
    bound: bool = True,
    own: str | None = None,
    watch_active: bool | None = True,
    domain_default: str | None = None,
) -> InfoItem:
    if domain_default is not None:
        session.add(
            Domain(name=host, default_watch_spec={"schema_version": 1, "interval": domain_default})
        )
    spec = {"schema_version": 1} | ({"interval": own} if own else {})
    item = InfoItem(name="profiled", watch_spec=spec, watch_active=watch_active)
    session.add(item)
    await session.flush()
    if bound:
        source = InfoSource(url=f"https://{host}/doc", source_specs=_SPECS, domain_name=host)
        session.add(source)
        await session.flush()
        session.add(
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
        )
        await session.flush()
    return item


async def _announced(session, item: InfoItem) -> list[dict]:
    rows = (
        await session.execute(
            select(ChangesOutboxRow.payload)
            .where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
            .order_by(ChangesOutboxRow.id)
        )
    ).scalars()
    return [p for p in rows if p["info_item_id"] == str(item.info_item_id)]


def _intervals(payloads: list[dict]) -> list[str | None]:
    return [p["watch_spec"].get("interval") for p in payloads]


# --- Writes ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_put_stores_todays_result_and_announces_it(session):
    item = await _item(session, own="1d")

    profile = await put_temporal_profile(
        session, item.info_item_id, _event(), today=date(2026, 4, 10)
    )

    assert (profile.resolved_interval, profile.evaluated_on) == ("1h", date(2026, 4, 10))
    assert _intervals(await _announced(session, item)) == ["1h"]


@pytest.mark.asyncio
async def test_a_put_that_resolves_nothing_today_announces_nothing(session):
    item = await _item(session, own="1d")

    profile = await put_temporal_profile(
        session, item.info_item_id, _event(), today=date(2026, 1, 1)
    )

    assert profile.resolved_interval is None
    assert await _announced(session, item) == []


@pytest.mark.asyncio
async def test_a_replace_announces_only_when_the_result_moves(session):
    item = await _item(session)
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 4, 10))

    # Same result (1h) with a different post-action: nothing on the wire moves.
    await put_temporal_profile(
        session, item.info_item_id, _event(post_action="deactivate"), today=date(2026, 4, 10)
    )
    # A slower tight rule: the result moves.
    await put_temporal_profile(
        session,
        item.info_item_id,
        _event(rules=[{"days_before": 7, "interval": "2h"}]),
        today=date(2026, 4, 10),
    )

    assert _intervals(await _announced(session, item)) == ["1h", "2h"]


@pytest.mark.asyncio
async def test_disabling_a_profile_releases_its_interval(session):
    item = await _item(session, own="1d")
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 4, 10))

    profile = await put_temporal_profile(
        session, item.info_item_id, _event(is_active=False), today=date(2026, 4, 10)
    )

    assert profile.resolved_interval is None
    assert _intervals(await _announced(session, item)) == ["1h", "1d"]


@pytest.mark.asyncio
async def test_a_put_re_arms_a_fired_profile(session):
    item = await _item(session)
    profile = await put_temporal_profile(
        session, item.info_item_id, _event(), today=date(2026, 4, 10)
    )
    profile.fired_at = datetime(2026, 4, 16, 0, 5, tzinfo=UTC)
    await session.flush()

    profile = await put_temporal_profile(
        session, item.info_item_id, _event(reference_date=date(2026, 5, 1)), today=date(2026, 4, 17)
    )

    assert profile.fired_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fields", "path"),
    [
        (_event(reference_date=None), "reference_date"),
        (_event(rules=[{"days_before": 7, "interval": "soon"}]), "rules/0/interval"),
        # The window ended yesterday: a re-arm here would fire again tomorrow.
        (_event(reference_date=date(2026, 4, 9)), "reference_date"),
        (
            {
                "profile_type": "seasonal",
                "reference_date": None,
                "date_range_start": date(2026, 3, 1),
                "date_range_end": date(2026, 4, 9),
                "rules": [{"interval": "1h"}],
                "post_action": "deactivate",
                "is_active": True,
            },
            "date_range_end",
        ),
    ],
)
async def test_an_invalid_put_is_refused_and_writes_nothing(session, fields, path):
    item = await _item(session)

    with pytest.raises(ProfileInvalid) as raised:
        await put_temporal_profile(session, item.info_item_id, fields, today=date(2026, 4, 10))

    assert path in [p for p, _m in raised.value.errors]
    assert await session.get(TemporalProfile, item.info_item_id) is None
    assert await _announced(session, item) == []


@pytest.mark.asyncio
async def test_a_window_ending_today_is_accepted(session):
    item = await _item(session)

    profile = await put_temporal_profile(session, item.info_item_id, _event(), today=REF)

    assert profile.resolved_interval == "1h"


@pytest.mark.asyncio
async def test_a_put_on_a_missing_item_is_none(session):
    assert (
        await put_temporal_profile(
            session, "01JZZZZZZZZZZZZZZZZZZZZZZZ", _event(), today=date(2026, 4, 10)
        )
        is None
    )


@pytest.mark.asyncio
async def test_a_put_on_an_unannounceable_item_stores_and_emits_nothing(session):
    """#167: policy cannot change announceability."""
    item = await _item(session, bound=False)

    profile = await put_temporal_profile(
        session, item.info_item_id, _event(), today=date(2026, 4, 10)
    )

    assert profile.resolved_interval == "1h"
    assert await _announced(session, item) == []


@pytest.mark.asyncio
async def test_delete_announces_the_tier_below_when_the_profile_held_one(session):
    item = await _item(session, own="1d")
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 4, 10))

    assert await delete_temporal_profile(session, item.info_item_id) is True

    assert await session.get(TemporalProfile, item.info_item_id) is None
    assert _intervals(await _announced(session, item)) == ["1h", "1d"]


@pytest.mark.asyncio
async def test_deleting_a_silent_profile_announces_nothing(session):
    item = await _item(session)
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 1, 1))

    assert await delete_temporal_profile(session, item.info_item_id) is True
    assert await _announced(session, item) == []


@pytest.mark.asyncio
async def test_deleting_no_profile_is_false(session):
    item = await _item(session)

    assert await delete_temporal_profile(session, item.info_item_id) is False


# --- The boundary ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_boundary_steps_and_announces_only_on_a_crossing(session):
    """The 30/7 profile: 6h from 30 days out, 1h from 7, silent after the date.
    Every day is evaluated; only a day the result moves announces, and once."""
    item = await _item(session, own="1d")
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 3, 1))

    for day in [date(2026, 3, d) for d in (14, 15, 16, 17)] + [date(2026, 4, d) for d in (7, 8)]:
        await evaluate_at_boundary(session, item.info_item_id, today=day)

    assert _intervals(await _announced(session, item)) == ["6h", "1h"]
    profile = await session.get(TemporalProfile, item.info_item_id)
    assert (profile.resolved_interval, profile.evaluated_on) == ("1h", date(2026, 4, 8))


@pytest.mark.asyncio
async def test_a_same_day_rerun_emits_nothing(session):
    item = await _item(session)
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 3, 1))
    await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 8))
    before = len(await _announced(session, item))

    outcome = await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 8))

    assert len(await _announced(session, item)) == before
    assert not outcome.announced


@pytest.mark.asyncio
async def test_deactivate_fires_once_the_day_after_and_announces_once(session):
    item = await _item(session, own="1d")
    await put_temporal_profile(
        session, item.info_item_id, _event(post_action="deactivate"), today=date(2026, 4, 10)
    )

    outcome = await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 16))
    again = await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 17))

    assert outcome.fired == "deactivate" and again.fired is None
    payloads = await _announced(session, item)
    # The put (1h), then the boundary once: interval released AND inactive together.
    assert [(p["watch_spec"].get("interval"), p["active"]) for p in payloads] == [
        ("1h", True),
        ("1d", False),
    ]
    profile = await session.get(TemporalProfile, item.info_item_id)
    assert profile.fired_at is not None
    assert item.watch_active is False


@pytest.mark.asyncio
async def test_archive_fires_through_the_lifecycle_and_announces_once(session):
    item = await _item(session, own="1d")
    await put_temporal_profile(
        session, item.info_item_id, _event(post_action="archive"), today=date(2026, 4, 10)
    )

    outcome = await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 16))

    assert outcome.fired == "archive"
    assert item.archived_at is not None
    assert item.watch_active is True  # archive is orthogonal to pause (#361)
    payloads = await _announced(session, item)
    assert [(p["watch_spec"].get("interval"), p["active"]) for p in payloads] == [
        ("1h", True),
        ("1d", False),
    ]


@pytest.mark.asyncio
async def test_archive_on_an_archived_item_still_announces_the_released_interval(session):
    item = await _item(session, own="1d")
    await put_temporal_profile(
        session, item.info_item_id, _event(post_action="archive"), today=date(2026, 4, 10)
    )
    item.archived_at = datetime(2026, 4, 12, tzinfo=UTC)
    await session.flush()

    await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 16))

    payloads = await _announced(session, item)
    assert [p["watch_spec"].get("interval") for p in payloads] == ["1h", "1d"]
    assert item.archived_at == datetime(2026, 4, 12, tzinfo=UTC)  # the first archive stands


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("own", "domain_default", "after"),
    [
        ("6h", None, "1d"),  # sub-1d base: slowed to 1d
        (None, "1h", "1d"),  # sub-1d base from the host's default: the item gets 1d
        ("7d", None, "7d"),  # already slower: not sped up (watcher#205)
        ("1d", None, "1d"),  # exactly 1d: nothing to do
        (None, None, None),  # no base (Watcher's 1d default): nothing to do
    ],
)
async def test_reduce_frequency_slows_only_a_sub_daily_base(session, own, domain_default, after):
    item = await _item(session, host="reduce.example.test", own=own, domain_default=domain_default)
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 4, 10))

    outcome = await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 16))

    assert outcome.fired == "reduce_frequency"
    assert item.watch_spec.get("interval") == after
    assert _intervals(await _announced(session, item))[-1] == (after or domain_default)


@pytest.mark.asyncio
async def test_a_post_action_fires_on_a_paused_item(session):
    """D4: Archiver owns the intent and its own clock; a pause does not delay it."""
    item = await _item(session, own="6h", watch_active=False)
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 4, 10))

    outcome = await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 16))

    assert outcome.fired == "reduce_frequency"
    assert item.watch_spec["interval"] == "1d"


@pytest.mark.asyncio
async def test_an_inactive_profile_never_fires(session):
    item = await _item(session, own="6h")
    await put_temporal_profile(
        session, item.info_item_id, _event(is_active=False), today=date(2026, 4, 10)
    )

    outcome = await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 16))

    assert outcome.fired is None
    assert item.watch_spec["interval"] == "6h"


@pytest.mark.asyncio
async def test_a_malformed_row_is_skipped_with_a_warning(session, caplog):
    """Watcher's tick raised on a bad row and stopped scheduling every item."""
    item = await _item(session)
    await put_temporal_profile(session, item.info_item_id, _event(), today=date(2026, 4, 10))
    profile = await session.get(TemporalProfile, item.info_item_id)
    profile.rules = [{"days_before": "seven", "interval": "1h"}]  # a hand-edit
    await session.flush()

    with caplog.at_level(logging.WARNING):
        outcome = await evaluate_at_boundary(session, item.info_item_id, today=date(2026, 4, 16))

    assert outcome.skipped
    assert [getattr(r, "info_item_id", None) for r in caplog.records] == [str(item.info_item_id)]
    assert profile.fired_at is None


@pytest.mark.asyncio
async def test_run_boundary_evaluates_every_profile_and_counts(session, caplog):
    stepping = await _item(session, host="a.example.test")
    firing = await _item(session, host="b.example.test", own="6h")
    quiet = await _item(session, host="c.example.test")
    await put_temporal_profile(session, stepping.info_item_id, _event(), today=date(2026, 4, 1))
    await put_temporal_profile(
        session,
        firing.info_item_id,
        _event(reference_date=date(2026, 4, 7)),
        today=date(2026, 4, 1),
    )
    await put_temporal_profile(
        session,
        quiet.info_item_id,
        _event(reference_date=date(2026, 12, 1)),
        today=date(2026, 4, 1),
    )
    await session.commit()

    with caplog.at_level(logging.INFO):
        counts = await run_boundary(session, today=date(2026, 4, 8))

    assert counts == {"evaluated": 3, "moved": 2, "fired": 1, "announced": 2, "skipped": 0}
    assert "temporal boundary finished" in caplog.text


# --- Races: #364's, with a profile write in place of a cadence write ----------


async def _until_waiting_on_a_lock(test_engine, pid: asyncio.Future, *, timeout=5.0) -> bool:
    """Proof that *this* backend is blocked on a lock (``test_domain_policy``'s helper)."""
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
            await conn.rollback()
            if waiting:
                return True
            await asyncio.sleep(0.05)
    return False


async def _committed_item(factory, committed_rows, host: str, **profile) -> ULID:
    async with factory() as setup:
        domain = Domain(name=host)
        item = InfoItem(name="race", watch_active=True)
        source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
        setup.add_all([domain, item, source])
        await setup.flush()
        binding = InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=source.info_source_id
        )
        setup.add(binding)
        if profile:
            await put_temporal_profile(setup, item.info_item_id, _event(), **profile)
        await setup.commit()
        committed_rows += [
            (Domain, domain.id),
            (InfoSource, source.info_source_id),
            (InfoItem, item.info_item_id),
            (InfoItemSource, binding.id),
        ]
        return item.info_item_id


async def _committed_payloads(factory, committed_rows, item_id: ULID) -> list[dict]:
    async with factory() as check:
        rows = list(
            (
                await check.execute(
                    select(ChangesOutboxRow)
                    .where(ChangesOutboxRow.topic == INFO_REGISTRY_TOPIC)
                    .order_by(ChangesOutboxRow.id)
                )
            ).scalars()
        )
    mine = [r for r in rows if r.payload["info_item_id"] == str(item_id)]
    committed_rows += [(ChangesOutboxRow, r.id) for r in mine]
    return [r.payload for r in mine]


async def _pid(session) -> int:
    return (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()


@pytest.mark.asyncio
async def test_a_domain_cadence_write_waits_for_a_profile_write_and_skips_its_item(
    test_engine, committed_rows
):
    """The fan-out locks the host's items, so it waits on the profile write's item
    lock; then it reads the committed profile and leaves the item alone - its
    profile wins over the new default (``_announce_moved``'s tier). Before #365
    it asked only "no own interval?" and would re-announce."""
    host = "race-profile.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    item_id = await _committed_item(factory, committed_rows, host)

    pid = asyncio.get_running_loop().create_future()

    async def _domain_write() -> None:
        async with factory() as s:
            pid.set_result(await _pid(s))
            await update_domain(
                s,
                host,
                {"default_watch_spec": {"schema_version": 1, "interval": "6h"}},
                create=False,
            )
            await s.commit()

    async with factory() as writer:
        await put_temporal_profile(writer, item_id, _event(), today=date(2026, 4, 10))
        task = asyncio.create_task(_domain_write())
        try:
            waited = await _until_waiting_on_a_lock(test_engine, pid)
            await writer.commit()
            await asyncio.wait_for(task, timeout=10)
        finally:
            task.cancel()
            await writer.rollback()
    assert waited, "the domain write must wait on the profile write's item lock"

    payloads = await _committed_payloads(factory, committed_rows, item_id)
    assert [p["watch_spec"] for p in payloads] == [{"schema_version": 1, "interval": "1h"}]


@pytest.mark.asyncio
async def test_a_profile_write_waits_for_a_domain_cadence_write_and_announces_last(
    test_engine, committed_rows
):
    """The other order: the profile write's item lock waits on the fan-out's, and
    its announcement - the profile's interval - is the item's last word."""
    host = "race-profile-2.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    item_id = await _committed_item(factory, committed_rows, host)

    pid = asyncio.get_running_loop().create_future()

    async def _profile_write() -> None:
        async with factory() as s:
            pid.set_result(await _pid(s))
            await put_temporal_profile(s, item_id, _event(), today=date(2026, 4, 10))
            await s.commit()

    async with factory() as writer:
        await update_domain(
            writer,
            host,
            {"default_watch_spec": {"schema_version": 1, "interval": "6h"}},
            create=False,
        )
        task = asyncio.create_task(_profile_write())
        try:
            waited = await _until_waiting_on_a_lock(test_engine, pid)
            await writer.commit()
            await asyncio.wait_for(task, timeout=10)
        finally:
            task.cancel()
            await writer.rollback()
    assert waited, "the profile write must wait on the domain write's item lock"

    payloads = await _committed_payloads(factory, committed_rows, item_id)
    assert [p["watch_spec"].get("interval") for p in payloads] == ["6h", "1h"]
    assert payloads[-1]["generation"] > payloads[0]["generation"]


@pytest.mark.asyncio
async def test_the_boundary_waits_for_a_profile_write_and_judges_the_committed_profile(
    test_engine, committed_rows
):
    """The job locks the item before it reads the profile, so a write in flight
    finishes first; the job then finds the result the write stored for today
    and announces nothing - one computation, one announcement."""
    host = "race-boundary.example.test"
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    item_id = await _committed_item(factory, committed_rows, host, today=date(2026, 3, 1))
    today = date(2026, 4, 10)

    pid = asyncio.get_running_loop().create_future()
    outcome: list[BoundaryOutcome] = []

    async def _job() -> None:
        async with factory() as s:
            pid.set_result(await _pid(s))
            outcome.append(await evaluate_at_boundary(s, item_id, today=today))
            await s.commit()

    async with factory() as writer:
        await put_temporal_profile(
            writer, item_id, _event(rules=[{"days_before": 7, "interval": "2h"}]), today=today
        )
        task = asyncio.create_task(_job())
        try:
            waited = await _until_waiting_on_a_lock(test_engine, pid)
            await writer.commit()
            await asyncio.wait_for(task, timeout=10)
        finally:
            task.cancel()
            await writer.rollback()
    assert waited, "the boundary must wait on the profile write's item lock"

    assert outcome == [BoundaryOutcome()]
    payloads = await _committed_payloads(factory, committed_rows, item_id)
    # The setup put (silent on 03-01: nothing), then the racing write's 2h.
    assert [p["watch_spec"].get("interval") for p in payloads] == ["2h"]
