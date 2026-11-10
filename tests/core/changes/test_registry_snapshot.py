"""The periodic full-set republish on ``info.registry`` (archiver#141).

Snapshots bypass the outbox, deliberately: a full republish every period would
put a whole key set through the drain on a timer, churning the table and the
live partial index (bounded since archiver#189's retention pass, but churn all
the same). The snapshot carries no transactional obligation - it is an
idempotent LWW read of current DB state, and the next period corrects a lost
one. The durability consequence
is real and stated: **this path has no retry**. A snapshot lost to a broker
outage is corrected by the next period, not by a re-attempt.

The full set is: every announceable item, live; every previously-announced but
currently unannounceable item (no active binding, or empty specs), revoked;
every deleted item from ``revoked_info_items``, revoked. Never-announced keys
are absent — no consumer knows them. Generations are **read, never bumped**:
a bump per republish would make every snapshot look like a mutation, race
concurrent deltas, and defeat apply-iff-greater.
"""

import asyncio
import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from co_core.pure.adapters.bus.envelope import payload_from_dict
from co_core_aio.bus import AsyncBusPublisher
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import registry_snapshot
from src.core.changes.registry_snapshot import (
    DEFAULT_REGISTRY_STREAM_MAXLEN,
    DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
    INFO_REGISTRY_TOPIC,
    MAXLEN_ENV,
    RETAINED_FULL_SETS,
    publish_full_set,
    resolve_registry_maxlen,
    resolve_snapshot_interval,
)
from src.core.models import (
    Domain,
    InfoItem,
    InfoItemSource,
    InfoSource,
    RevokedInfoItem,
    TemporalProfile,
)

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]
_HOSTS = ".snapshot.test"  # suffix of every Domain this module commits


@pytest.fixture
async def fake_redis():
    client = fakeredis_aio.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def no_maxlen_override(monkeypatch):
    """Production leaves the override unset; so does every case unless it sets it."""
    monkeypatch.delenv(MAXLEN_ENV, raising=False)


@pytest.fixture
def publisher(fake_redis):
    return AsyncBusPublisher(fake_redis)


@pytest.fixture
async def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def clean_tables(test_engine):
    tables = "information.info_item_sources, information.revoked_info_items"
    async with test_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables}"))
        await conn.execute(text("DELETE FROM information.info_items"))
        await conn.execute(text("DELETE FROM information.info_sources"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables}"))
        await conn.execute(text("DELETE FROM information.info_items"))
        await conn.execute(text("DELETE FROM information.info_sources"))
        await conn.execute(text(f"DELETE FROM information.domains WHERE name LIKE '%{_HOSTS}'"))


async def _seed(session_factory) -> dict:
    """One of each kind: live, unbound-but-announced, never-announced, deleted."""
    async with session_factory() as s:
        live = InfoItem(name="live", announcement_generation=3)
        unbound = InfoItem(name="unbound", announcement_generation=2)
        never = InfoItem(name="never")  # generation 0, no binding
        source = InfoSource(url="https://example.test/live", source_specs=_SPECS)
        s.add_all([live, unbound, never, source])
        await s.flush()
        s.add(InfoItemSource(info_item_id=live.info_item_id, info_source_id=source.info_source_id))
        deleted_id = "01JZZZZZZZZZZZZZZZZZZZZZZZ"
        s.add(RevokedInfoItem(info_item_id=deleted_id, generation=5))
        await s.commit()
        return {
            "live": str(live.info_item_id),
            "unbound": str(unbound.info_item_id),
            "never": str(never.info_item_id),
            "deleted": deleted_id,
        }


async def _stream_payloads(fake_redis) -> list[dict]:
    entries = await fake_redis.xrange("info.registry")
    return [json.loads(fields[b"payload"]) for _id, fields in entries]


@pytest.mark.asyncio
async def test_full_set_covers_live_revoked_and_deleted(session_factory, publisher, fake_redis):
    ids = await _seed(session_factory)

    result = await publish_full_set(session_factory=session_factory, publisher=publisher)

    assert (result.live, result.revoked) == (1, 2)
    payloads = {p["info_item_id"]: p for p in await _stream_payloads(fake_redis)}
    assert set(payloads) == {ids["live"], ids["unbound"], ids["deleted"]}

    assert payloads[ids["live"]]["revoked"] is False
    assert payloads[ids["live"]]["generation"] == 3
    assert payloads[ids["live"]]["url"] == "https://example.test/live"

    assert payloads[ids["unbound"]]["revoked"] is True
    assert payloads[ids["unbound"]]["generation"] == 2

    assert payloads[ids["deleted"]]["revoked"] is True
    assert payloads[ids["deleted"]]["generation"] == 5

    for p in payloads.values():
        payload_from_dict(p)  # every published entry honours the contract


@pytest.mark.asyncio
async def test_full_set_resolves_each_items_host_through_the_shared_rule(
    session_factory, publisher, fake_redis
):
    """archiver#360: the snapshot and the delta path resolve ``active`` alike.

    Suspended host → ``false``; active host and row-less host → ``watch_active``,
    ``NULL`` kept as ``NULL``.
    """
    cases = {
        "off": (Domain(name=f"off{_HOSTS}", is_active=False), True),
        "archived": (Domain(name=f"archived{_HOSTS}", archived_at=datetime.now(UTC)), None),
        "on": (Domain(name=f"on{_HOSTS}"), None),
        "norow": (None, True),
    }
    ids = {}
    async with session_factory() as s:
        for label, (domain, watch_active) in cases.items():
            if domain is not None:
                s.add(domain)
            item = InfoItem(name=label, watch_active=watch_active, announcement_generation=1)
            source = InfoSource(
                url=f"https://{label}{_HOSTS}/x",
                source_specs=_SPECS,
                domain_name=f"{label}{_HOSTS}",
            )
            s.add_all([item, source])
            await s.flush()
            s.add(
                InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
            )
            ids[label] = str(item.info_item_id)
        await s.commit()

    await publish_full_set(session_factory=session_factory, publisher=publisher)

    active = {p["info_item_id"]: p["active"] for p in await _stream_payloads(fake_redis)}
    assert {label: active[i] for label, i in ids.items()} == {
        "off": False,
        "archived": False,
        "on": None,
        "norow": True,
    }


@pytest.mark.asyncio
async def test_full_set_announces_an_archived_item_inactive(session_factory, publisher, fake_redis):
    """archiver#361: the snapshot replays what the delta said for an archived item."""
    async with session_factory() as s:
        item = InfoItem(
            name="archived",
            watch_active=True,
            archived_at=datetime.now(UTC),
            announcement_generation=1,
        )
        source = InfoSource(url="https://example.test/archived", source_specs=_SPECS)
        s.add_all([item, source])
        await s.flush()
        s.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id))
        await s.commit()
        item_id = str(item.info_item_id)

    await publish_full_set(session_factory=session_factory, publisher=publisher)

    (payload,) = [p for p in await _stream_payloads(fake_redis) if p["info_item_id"] == item_id]
    assert payload["active"] is False
    assert payload["revoked"] is False


@pytest.mark.asyncio
async def test_full_set_announces_the_resolved_cadence(session_factory, publisher, fake_redis):
    """archiver#364: the snapshot resolves cadence through the same builder.

    Item tier, then the host's default, then nothing (Watcher's default).
    """
    cases = {
        "own": ({"schema_version": 1, "interval": "1h"}, {"schema_version": 1, "interval": "6h"}),
        "inherits": ({"schema_version": 1}, {"schema_version": 1, "interval": "6h"}),
        "neither": ({"schema_version": 1}, None),
    }
    ids = {}
    async with session_factory() as s:
        for label, (own, default) in cases.items():
            host = f"cadence-{label}{_HOSTS}"
            s.add(Domain(name=host, default_watch_spec=default))
            item = InfoItem(name=label, watch_spec=own, announcement_generation=1)
            source = InfoSource(url=f"https://{host}/x", source_specs=_SPECS, domain_name=host)
            s.add_all([item, source])
            await s.flush()
            s.add(
                InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
            )
            ids[label] = str(item.info_item_id)
        await s.commit()

    await publish_full_set(session_factory=session_factory, publisher=publisher)

    specs = {p["info_item_id"]: p["watch_spec"] for p in await _stream_payloads(fake_redis)}
    assert {label: specs[i] for label, i in ids.items()} == {
        "own": {"schema_version": 1, "interval": "1h"},
        "inherits": {"schema_version": 1, "interval": "6h"},
        "neither": {"schema_version": 1},
    }


@pytest.mark.asyncio
async def test_full_set_replays_the_profiles_stored_result(session_factory, publisher, fake_redis):
    """archiver#365 (D1): the snapshot never reads the clock. This profile's
    window ended long ago - evaluated today it would say nothing - but the
    stored result is what the last delta announced, so it is what replays, at
    the stored generation."""
    async with session_factory() as s:
        item = InfoItem(
            name="profiled",
            watch_spec={"schema_version": 1, "interval": "1d"},
            announcement_generation=4,
        )
        source = InfoSource(url="https://example.test/profiled", source_specs=_SPECS)
        s.add_all([item, source])
        await s.flush()
        s.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id))
        s.add(
            TemporalProfile(
                info_item_id=item.info_item_id,
                profile_type="event",
                reference_date=date(2020, 1, 1),
                rules=[{"days_before": 7, "interval": "1h"}],
                post_action="deactivate",
                resolved_interval="1h",
                evaluated_on=date(2019, 12, 30),
            )
        )
        await s.commit()
        item_id = str(item.info_item_id)

    await publish_full_set(session_factory=session_factory, publisher=publisher)

    (payload,) = [p for p in await _stream_payloads(fake_redis) if p["info_item_id"] == item_id]
    assert payload["watch_spec"] == {"schema_version": 1, "interval": "1h"}
    assert payload["generation"] == 4


@pytest.mark.asyncio
async def test_snapshot_reads_generations_and_never_bumps(session_factory, publisher, fake_redis):
    ids = await _seed(session_factory)

    await publish_full_set(session_factory=session_factory, publisher=publisher)
    await publish_full_set(session_factory=session_factory, publisher=publisher)

    async with session_factory() as s:
        gen = (
            await s.execute(
                text(
                    "SELECT announcement_generation FROM information.info_items"
                    " WHERE info_item_id = :i"
                ),
                {"i": ids["live"]},
            )
        ).scalar_one()
    assert gen == 3  # untouched by two republishes

    payloads = await _stream_payloads(fake_redis)
    live = [p for p in payloads if p["info_item_id"] == ids["live"]]
    assert [p["generation"] for p in live] == [3, 3]  # identical; consumer ignores the repeat


@pytest.mark.asyncio
async def test_bound_item_with_empty_specs_republishes_as_revoked(
    session_factory, publisher, fake_redis
):
    """Same announceability rule as the delta path — co-core refuses live with
    empty source_specs, and the snapshot must not diverge from the deltas."""
    async with session_factory() as s:
        item = InfoItem(name="specless", announcement_generation=4)
        source = InfoSource(url="https://example.test/none", source_specs=[])
        s.add_all([item, source])
        await s.flush()
        s.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id))
        await s.commit()
        item_id = str(item.info_item_id)

    await publish_full_set(session_factory=session_factory, publisher=publisher)

    (payload,) = await _stream_payloads(fake_redis)
    assert payload["info_item_id"] == item_id
    assert payload["revoked"] is True
    assert payload["generation"] == 4


@pytest.mark.asyncio
async def test_one_failed_publish_does_not_abort_the_set(session_factory, fake_redis):
    """No retry, no abort: the set is idempotent state, absence is not a signal,
    and the next period corrects whatever was lost. One broken entry must not
    cost the other keys their republish."""
    await _seed(session_factory)
    real = AsyncBusPublisher(fake_redis)
    calls = {"n": 0}

    class FlakyPublisher:
        async def execute(self, effect):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("broker blip")
            return await real.execute(effect)

    result = await publish_full_set(session_factory=session_factory, publisher=FlakyPublisher())

    assert result.live + result.revoked == 2  # 3 entries attempted, 1 lost, 2 landed
    assert len(await _stream_payloads(fake_redis)) == 2


class _SpyPublisher:
    """Records every effect, then publishes it for real."""

    def __init__(self, fake_redis):
        self.captured: list = []
        self._real = AsyncBusPublisher(fake_redis)

    async def execute(self, effect):
        self.captured.append(effect)
        return await self._real.execute(effect)


def test_the_cap_constants_are_the_ones_broker_mirrors():
    """archiver#373 item 4: ``info.registry`` takes ``content.fetch-policy``'s rule.

    CannObserv/broker#139 mirrors all three by these names in
    ``src/broker/bus_health.py`` (``REGISTRY_PRODUCER_MAXLEN``,
    ``REGISTRY_RETAINED_FULL_SETS``, ``REGISTRY_REPUBLISH_PERIOD_SECONDS``), and
    its tests cite this module's names. Moving one is a commit there first.
    """
    assert DEFAULT_REGISTRY_STREAM_MAXLEN == 1_000
    assert RETAINED_FULL_SETS == 10
    assert DEFAULT_SNAPSHOT_INTERVAL_SECONDS == 3600
    assert MAXLEN_ENV == "ARCHIVER_REGISTRY_STREAM_MAXLEN"


@pytest.mark.asyncio
async def test_a_small_set_carries_the_default_cap(session_factory, fake_redis):
    """Three entries x 10 is under 1,000, so the default governs.

    Retention rides the publish for a config/state stream (consumer contract,
    replay-from-0-0); the operator XTRIM loop explicitly excludes this topic.
    """
    await _seed(session_factory)
    spy = _SpyPublisher(fake_redis)

    result = await publish_full_set(session_factory=session_factory, publisher=spy)

    assert result.maxlen == DEFAULT_REGISTRY_STREAM_MAXLEN
    assert len(spy.captured) == 3
    assert all(e.maxlen == DEFAULT_REGISTRY_STREAM_MAXLEN for e in spy.captured)


@pytest.mark.asyncio
async def test_the_floor_counts_tombstones_and_raises_the_cap(
    session_factory, fake_redis, monkeypatch
):
    """Cap = max(default, RETAINED_FULL_SETS x full set), tombstones included.

    The seed is 1 live + 2 revoked. At x500 the floor is 1,500: counting live
    entries alone would give 500 and leave the default in charge, so 1,500
    proves the tombstones are counted. A tombstone that ages out of the stream
    un-revokes its key for a ``0-0`` consumer.
    """
    await _seed(session_factory)
    monkeypatch.setattr(registry_snapshot, "RETAINED_FULL_SETS", 500)
    spy = _SpyPublisher(fake_redis)

    result = await publish_full_set(session_factory=session_factory, publisher=spy)

    assert result.maxlen == 1_500
    assert all(e.maxlen == 1_500 for e in spy.captured)


@pytest.mark.asyncio
async def test_the_floor_counts_entries_built_not_entries_landed(session_factory, fake_redis):
    """A publish that fails mid-set must not shrink the cap the set computed."""
    await _seed(session_factory)
    real = AsyncBusPublisher(fake_redis)
    calls = {"n": 0}

    class FlakyPublisher:
        async def execute(self, effect):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("broker blip")
            return await real.execute(effect)

    result = await publish_full_set(session_factory=session_factory, publisher=FlakyPublisher())

    assert result.maxlen == DEFAULT_REGISTRY_STREAM_MAXLEN


@pytest.mark.asyncio
async def test_the_override_raises_the_cap(session_factory, fake_redis, monkeypatch):
    await _seed(session_factory)
    monkeypatch.setenv(MAXLEN_ENV, "5000")
    spy = _SpyPublisher(fake_redis)

    result = await publish_full_set(session_factory=session_factory, publisher=spy)

    assert result.maxlen == 5_000
    assert all(e.maxlen == 5_000 for e in spy.captured)


@pytest.mark.asyncio
async def test_the_override_never_drops_the_cap_below_the_floor(
    session_factory, fake_redis, monkeypatch
):
    """Before archiver#373 the override could set any cap; now the floor wins."""
    await _seed(session_factory)
    monkeypatch.setattr(registry_snapshot, "RETAINED_FULL_SETS", 500)
    monkeypatch.setenv(MAXLEN_ENV, "1200")

    result = await publish_full_set(
        session_factory=session_factory, publisher=_SpyPublisher(fake_redis)
    )

    assert result.maxlen == 1_500


def test_resolve_registry_maxlen():
    """Defensive parse, floored: never unbounded, never under the floor."""
    assert resolve_registry_maxlen(None) == DEFAULT_REGISTRY_STREAM_MAXLEN
    assert resolve_registry_maxlen("  ") == DEFAULT_REGISTRY_STREAM_MAXLEN
    assert resolve_registry_maxlen(None, floor=2_000) == 2_000
    assert resolve_registry_maxlen("5000", floor=2_000) == 5_000
    assert resolve_registry_maxlen("1200", floor=2_000) == 2_000
    assert resolve_registry_maxlen("nonsense") == DEFAULT_REGISTRY_STREAM_MAXLEN
    assert resolve_registry_maxlen("nonsense", floor=2_000) == 2_000
    assert resolve_registry_maxlen("0") == DEFAULT_REGISTRY_STREAM_MAXLEN
    assert resolve_registry_maxlen("-5") == DEFAULT_REGISTRY_STREAM_MAXLEN


def test_an_override_under_the_floor_is_reported(monkeypatch):
    """The one misconfiguration the floor overrides, so it is said out loud.

    Spies the module logger rather than using caplog: configure_logging()
    replaces root.handlers, which defeats pytest's capture handler.
    """
    spy = MagicMock()
    monkeypatch.setattr(registry_snapshot.logger, "warning", spy)

    resolve_registry_maxlen("1200", floor=2_000)

    spy.assert_called_once()
    assert spy.call_args.kwargs["extra"] == {"value": "1200", "floor": 2_000, "effective": 2_000}


@pytest.mark.asyncio
async def test_run_hands_each_sets_cap_to_the_drain_and_logs_it(
    session_factory, publisher, fake_redis, monkeypatch
):
    """Deltas carry the last complete set's cap, read off ``topic_maxlen``.

    Only the snapshot computes the floor; the drain reads this mapping per
    row, so a delta never trims below RETAINED_FULL_SETS sets. The log line
    carries the cap: the deploy read-back for broker#139 is that line.
    """
    await _seed(session_factory)
    monkeypatch.setattr(registry_snapshot, "RETAINED_FULL_SETS", 500)
    info = MagicMock()
    monkeypatch.setattr(registry_snapshot.logger, "info", info)
    stop = asyncio.Event()
    topic_maxlen: dict[str, int] = {}

    task = asyncio.create_task(
        registry_snapshot.run(
            session_factory=session_factory,
            publisher=publisher,
            interval=3600,
            topic_maxlen=topic_maxlen,
            stop_event=stop,
        )
    )
    for _ in range(200):
        if topic_maxlen:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    assert topic_maxlen == {INFO_REGISTRY_TOPIC: 1_500}
    info.assert_called_once()
    assert info.call_args.args[0] == "Registry snapshot published"
    assert info.call_args.kwargs["extra"] == {
        "live": 1,
        "revoked": 2,
        "maxlen": 1_500,
        "interval_seconds": 3600,
    }


@pytest.mark.asyncio
async def test_run_publishes_at_start_on_trigger_and_on_stop(
    session_factory, publisher, fake_redis
):
    """The loop publishes immediately at startup (a restart converges consumers
    without waiting a period), then on each interval or operator trigger."""
    await _seed(session_factory)
    stop = asyncio.Event()
    trigger = asyncio.Event()

    task = asyncio.create_task(
        registry_snapshot.run(
            session_factory=session_factory,
            publisher=publisher,
            interval=3600,  # never fires within the test
            topic_maxlen={},
            stop_event=stop,
            trigger=trigger,
        )
    )
    for _ in range(200):  # wait for the startup set (3 entries)
        if len(await _stream_payloads(fake_redis)) >= 3:
            break
        await asyncio.sleep(0.01)
    assert len(await _stream_payloads(fake_redis)) == 3

    trigger.set()
    for _ in range(200):
        if len(await _stream_payloads(fake_redis)) >= 6:
            break
        await asyncio.sleep(0.01)
    assert len(await _stream_payloads(fake_redis)) == 6
    assert not trigger.is_set()  # consumed, not left latched

    stop.set()
    await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_run_survives_a_failing_publish_cycle(session_factory, fake_redis):
    """A cycle that raises is logged and the loop continues to the next one —
    the next period is the repair mechanism, so the loop dying IS the failure."""
    await _seed(session_factory)
    stop = asyncio.Event()
    trigger = asyncio.Event()
    real = AsyncBusPublisher(fake_redis)
    calls = {"n": 0}

    class FailsFirstCycle:
        async def execute(self, effect):
            calls["n"] += 1
            if calls["n"] <= 3:  # the whole first (startup) set
                raise ConnectionError("broker down")
            return await real.execute(effect)

    task = asyncio.create_task(
        registry_snapshot.run(
            session_factory=session_factory,
            publisher=FailsFirstCycle(),
            interval=3600,
            topic_maxlen={},
            stop_event=stop,
            trigger=trigger,
        )
    )
    for _ in range(200):
        if calls["n"] >= 3:
            break
        await asyncio.sleep(0.01)
    trigger.set()  # second cycle succeeds
    for _ in range(200):
        if len(await _stream_payloads(fake_redis)) >= 3:
            break
        await asyncio.sleep(0.01)
    assert len(await _stream_payloads(fake_redis)) == 3

    stop.set()
    await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_a_live_entry_at_generation_zero_is_published_and_reported(
    session_factory, publisher, fake_redis, monkeypatch
):
    """Generation 0 must not reach the wire as a live announcement (archiver#161).

    The delta path cannot produce one — ``_bump_generations`` increments before
    the payload is built, so its floor is 1. Only the snapshot can, by reading a
    row that never passed an announce site: pre-``f5c522f65657`` rows carrying
    the column's ``server_default`` of 0. The backfill migration removes that
    population, and after it a live 0 means a *missing announce call site* — an
    announceable item that mutated without announcing. Alarm on it.

    Publish it anyway. Skipping would drop a real item from the registry, and
    bumping here would violate this module's read-never-bump rule and race the
    delta path for the counter. Loud is the remedy; silent omission is not.

    Spies the module logger rather than using caplog: configure_logging()
    replaces root.handlers, which defeats pytest's capture handler.
    """
    async with session_factory() as s:
        item = InfoItem(name="unbumped")  # generation 0 — legacy shape
        source = InfoSource(url="https://example.test/legacy", source_specs=_SPECS)
        s.add_all([item, source])
        await s.flush()
        s.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id))
        await s.commit()
        item_id = str(item.info_item_id)

    spy = MagicMock()
    monkeypatch.setattr(registry_snapshot.logger, "warning", spy)

    result = await publish_full_set(session_factory=session_factory, publisher=publisher)

    assert (result.live, result.revoked) == (1, 0)
    (payload,) = await _stream_payloads(fake_redis)
    assert payload["info_item_id"] == item_id
    assert payload["revoked"] is False

    spy.assert_called_once()
    assert "generation 0" in spy.call_args.args[0]
    assert spy.call_args.kwargs["extra"]["info_item_id"] == item_id


@pytest.mark.asyncio
async def test_a_healthy_full_set_reports_no_generation_anomaly(
    session_factory, publisher, monkeypatch
):
    """The alarm above must stay silent on ordinary state, or it is noise."""
    await _seed(session_factory)
    spy = MagicMock()
    monkeypatch.setattr(registry_snapshot.logger, "warning", spy)

    await publish_full_set(session_factory=session_factory, publisher=publisher)

    spy.assert_not_called()


def test_interval_env_parsing():
    assert resolve_snapshot_interval(None) == DEFAULT_SNAPSHOT_INTERVAL_SECONDS
    assert resolve_snapshot_interval("900") == 900
    assert resolve_snapshot_interval("nonsense") == DEFAULT_SNAPSHOT_INTERVAL_SECONDS
    assert resolve_snapshot_interval("-5") == DEFAULT_SNAPSHOT_INTERVAL_SECONDS
