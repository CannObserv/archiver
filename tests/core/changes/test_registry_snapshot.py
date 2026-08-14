"""The periodic full-set republish on ``info.registry`` (archiver#141).

Snapshots bypass the outbox, deliberately: there is no pruner on
``changes_outbox``, so a periodic full republish through it grows the table
without bound and taxes the drain's ``published_at IS NULL`` scan. The snapshot
carries no transactional obligation — it is an idempotent LWW read of current
DB state, and the next period corrects a lost one. The durability consequence
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
    publish_full_set,
    resolve_registry_maxlen,
    resolve_snapshot_interval,
)
from src.core.models import InfoItem, InfoItemSource, InfoSource, RevokedInfoItem

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]


@pytest.fixture
async def fake_redis():
    client = fakeredis_aio.FakeRedis()
    yield client
    await client.aclose()


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

    live_count, revoked_count = await publish_full_set(
        session_factory=session_factory, publisher=publisher, maxlen=1000
    )

    assert (live_count, revoked_count) == (1, 2)
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
async def test_snapshot_reads_generations_and_never_bumps(session_factory, publisher, fake_redis):
    ids = await _seed(session_factory)

    await publish_full_set(session_factory=session_factory, publisher=publisher, maxlen=1000)
    await publish_full_set(session_factory=session_factory, publisher=publisher, maxlen=1000)

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

    await publish_full_set(session_factory=session_factory, publisher=publisher, maxlen=1000)

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

    live, revoked = await publish_full_set(
        session_factory=session_factory, publisher=FlakyPublisher(), maxlen=1000
    )

    assert live + revoked == 2  # 3 entries attempted, 1 lost, 2 landed
    assert len(await _stream_payloads(fake_redis)) == 2


@pytest.mark.asyncio
async def test_publishes_carry_the_registry_maxlen(session_factory, fake_redis):
    """Retention rides the publish for a config/state stream (consumer contract,
    replay-from-0-0) — the operator XTRIM loop explicitly excludes this topic."""
    await _seed(session_factory)
    captured = []
    real = AsyncBusPublisher(fake_redis)

    class SpyPublisher:
        async def execute(self, effect):
            captured.append(effect)
            return await real.execute(effect)

    await publish_full_set(session_factory=session_factory, publisher=SpyPublisher(), maxlen=777)

    assert captured and all(e.maxlen == 777 for e in captured)


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
            maxlen=1000,
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
            maxlen=1000,
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

    The delta path cannot produce one — ``_bump_generation`` increments before
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

    live, revoked = await publish_full_set(
        session_factory=session_factory, publisher=publisher, maxlen=1000
    )

    assert (live, revoked) == (1, 0)
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

    await publish_full_set(session_factory=session_factory, publisher=publisher, maxlen=1000)

    spy.assert_not_called()


def test_interval_and_maxlen_env_parsing():
    assert resolve_snapshot_interval(None) == DEFAULT_SNAPSHOT_INTERVAL_SECONDS
    assert resolve_snapshot_interval("900") == 900
    assert resolve_snapshot_interval("nonsense") == DEFAULT_SNAPSHOT_INTERVAL_SECONDS
    assert resolve_snapshot_interval("-5") == DEFAULT_SNAPSHOT_INTERVAL_SECONDS
    assert resolve_registry_maxlen(None) == DEFAULT_REGISTRY_STREAM_MAXLEN
    assert resolve_registry_maxlen("123") == 123
    assert resolve_registry_maxlen("0") == DEFAULT_REGISTRY_STREAM_MAXLEN
