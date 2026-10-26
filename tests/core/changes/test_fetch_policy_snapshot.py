"""The ``content.fetch-policy`` full set (archiver#366).

Every Domain emits one frame (a suspended one ``revoked`` with no interval),
every tombstone emits ``revoked``, every frame carries its stored generation,
and the retention cap is floored at ``RETAINED_FULL_SETS`` complete sets.
"""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from co_core.pure.adapters.bus.envelope import payload_from_dict
from co_core_aio.bus import AsyncBusPublisher
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import fetch_policy_snapshot
from src.core.changes.fetch_policy_snapshot import (
    DEFAULT_FETCH_POLICY_STREAM_MAXLEN,
    REPUBLISH_PERIOD_SECONDS,
    RETAINED_FULL_SETS,
    build_policy_events,
    publish_full_policy_set,
    resolve_fetch_policy_maxlen,
)
from src.core.models import Domain, FetchPolicyTombstone
from src.core.services.fetch_policy import FETCH_POLICY_TOPIC

_HOSTS = ".fpsnap.test"  # suffix of every host this module commits


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
async def clean(test_engine):
    async def _sweep():
        async with test_engine.begin() as conn:
            await conn.execute(text(f"DELETE FROM information.domains WHERE name LIKE '%{_HOSTS}'"))
            await conn.execute(
                text(f"DELETE FROM information.fetch_policy_tombstones WHERE host LIKE '%{_HOSTS}'")
            )

    await _sweep()
    yield
    await _sweep()


async def _seed(session_factory) -> dict[str, int]:
    """A live host, an inactive one, an archived one, and a deleted one."""
    async with session_factory() as s:
        s.add_all(
            [
                Domain(name=f"live{_HOSTS}", min_interval_seconds=2.5),
                Domain(name=f"inactive{_HOSTS}", is_active=False),
                Domain(name=f"archived{_HOSTS}", archived_at=datetime.now(UTC)),
                FetchPolicyTombstone(host=f"gone{_HOSTS}", generation=7),
            ]
        )
        await s.commit()
        rows = (
            await s.execute(
                text(
                    "SELECT name, fetch_policy_generation FROM information.domains"
                    f" WHERE name LIKE '%{_HOSTS}'"
                )
            )
        ).all()
    return {**dict(rows), f"gone{_HOSTS}": 7}


async def _frames(fake_redis) -> list:
    entries = await fake_redis.xrange(FETCH_POLICY_TOPIC)
    frames = [payload_from_dict(json.loads(fields[b"payload"])) for _id, fields in entries]
    return [f for f in frames if f.host.endswith(_HOSTS)]


@pytest.mark.asyncio
async def test_full_set_covers_live_suspended_and_deleted_hosts(
    session_factory, publisher, fake_redis
):
    generations = await _seed(session_factory)

    await publish_full_policy_set(session_factory=session_factory, publisher=publisher)

    frames = {f.host: f for f in await _frames(fake_redis)}
    assert set(frames) == set(generations)
    live = frames[f"live{_HOSTS}"]
    assert (live.revoked, live.min_interval_seconds) == (False, 2.5)
    for host in (f"inactive{_HOSTS}", f"archived{_HOSTS}", f"gone{_HOSTS}"):
        assert (frames[host].revoked, frames[host].min_interval_seconds) == (True, None)
    assert {h: f.generation for h, f in frames.items()} == generations


@pytest.mark.asyncio
async def test_every_frame_carries_a_generation(session_factory, publisher, fake_redis):
    """The guard: FetchPolicyEmit would accept None until cannobserv#579."""
    await _seed(session_factory)
    await publish_full_policy_set(session_factory=session_factory, publisher=publisher)
    frames = await _frames(fake_redis)
    assert frames
    assert all(isinstance(f.generation, int) for f in frames)


@pytest.mark.asyncio
async def test_the_full_set_reads_generations_and_never_draws(
    session_factory, publisher, fake_redis
):
    generations = await _seed(session_factory)
    await publish_full_policy_set(session_factory=session_factory, publisher=publisher)
    await publish_full_policy_set(session_factory=session_factory, publisher=publisher)
    assert (await _seed_generations(session_factory)) == {
        h: g for h, g in generations.items() if not h.startswith("gone")
    }


async def _seed_generations(session_factory) -> dict[str, int]:
    async with session_factory() as s:
        return dict(
            (
                await s.execute(
                    text(
                        "SELECT name, fetch_policy_generation FROM information.domains"
                        f" WHERE name LIKE '%{_HOSTS}'"
                    )
                )
            ).all()
        )


def test_an_unpublishable_host_is_skipped_with_a_warning(caplog):
    events = build_policy_events(
        [
            Domain(name=f"ok{_HOSTS}", fetch_policy_generation=1, min_interval_seconds=1.0),
            Domain(name="has space.example", fetch_policy_generation=2, min_interval_seconds=1.0),
        ],
        [FetchPolicyTombstone(host="bad host.example", generation=3)],
    )
    assert [e.host for e in events] == [f"ok{_HOSTS}"]
    assert caplog.text.count("skipping unpublishable fetch-policy host") == 2


@pytest.mark.asyncio
async def test_the_cap_is_floored_at_ten_complete_sets(session_factory, monkeypatch):
    """With the floor above the configured cap, every publish carries the floor."""
    await _seed(session_factory)
    monkeypatch.setenv(fetch_policy_snapshot.MAXLEN_ENV, "2")
    seen: list[int | None] = []

    class SpyPublisher:
        async def execute(self, publish):
            assert publish.topic == FETCH_POLICY_TOPIC
            seen.append(publish.maxlen)

    result = await publish_full_policy_set(
        session_factory=session_factory, publisher=SpyPublisher()
    )

    assert result.published == len(seen) >= 4
    assert result.maxlen == len(seen) * RETAINED_FULL_SETS
    assert set(seen) == {result.maxlen}


@pytest.mark.asyncio
async def test_one_failed_publish_does_not_abort_the_set(session_factory):
    await _seed(session_factory)
    calls = 0

    class FlakyPublisher:
        async def execute(self, publish):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("broker hiccup")

    result = await publish_full_policy_set(
        session_factory=session_factory, publisher=FlakyPublisher()
    )
    assert result.published == calls - 1


@pytest.mark.parametrize(
    ("raw", "floor", "expected"),
    [
        (None, 1, DEFAULT_FETCH_POLICY_STREAM_MAXLEN),
        ("", 1, DEFAULT_FETCH_POLICY_STREAM_MAXLEN),
        ("800", 1, 800),
        ("abc", 1, DEFAULT_FETCH_POLICY_STREAM_MAXLEN),
        ("0", 1, DEFAULT_FETCH_POLICY_STREAM_MAXLEN),
        ("-5", 1, DEFAULT_FETCH_POLICY_STREAM_MAXLEN),
        (None, 900, 900),
        ("800", 900, 900),
        ("abc", 900, 900),
    ],
)
def test_maxlen_resolver_is_bounded_and_floored(raw, floor, expected):
    assert resolve_fetch_policy_maxlen(raw, floor=floor) == expected


def test_the_three_broker_mirrored_numbers():
    """CannObserv/broker mirrors all three (LWW_PRODUCER_MAXLEN,
    LWW_RETAINED_FULL_SETS, LWW_REPUBLISH_PERIOD_SECONDS). File there before
    changing any of them."""
    assert DEFAULT_FETCH_POLICY_STREAM_MAXLEN == 500
    assert RETAINED_FULL_SETS == 10
    assert REPUBLISH_PERIOD_SECONDS == 300


@pytest.mark.asyncio
async def test_run_publishes_at_start_and_hands_the_cap_to_the_deltas(
    session_factory, publisher, fake_redis, monkeypatch
):
    """Deltas ride the outbox with the last complete set's cap, so a delta's
    ``MAXLEN ~`` never trims the stream below the full-set floor."""
    await _seed(session_factory)
    monkeypatch.setenv(fetch_policy_snapshot.MAXLEN_ENV, "2")
    topic_maxlen: dict[str, int] = {FETCH_POLICY_TOPIC: 2}
    stop = asyncio.Event()

    task = asyncio.create_task(
        fetch_policy_snapshot.run(
            session_factory=session_factory,
            publisher=publisher,
            stop_event=stop,
            topic_maxlen=topic_maxlen,
            interval=3600,
        )
    )
    for _ in range(100):
        if await _frames(fake_redis):
            break
        await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    published = await fake_redis.xlen(FETCH_POLICY_TOPIC)
    assert published >= 4
    assert topic_maxlen[FETCH_POLICY_TOPIC] == published * RETAINED_FULL_SETS


@pytest.mark.asyncio
async def test_run_survives_a_failing_cycle(session_factory, monkeypatch, caplog):
    stop = asyncio.Event()
    cycles = 0

    async def boom(**_kw):
        nonlocal cycles
        cycles += 1
        if cycles >= 2:
            stop.set()
        raise RuntimeError("db down")

    monkeypatch.setattr(fetch_policy_snapshot, "publish_full_policy_set", boom)
    await asyncio.wait_for(
        fetch_policy_snapshot.run(
            session_factory=session_factory,
            publisher=object(),
            stop_event=stop,
            topic_maxlen={},
            interval=0.01,
        ),
        timeout=5,
    )
    assert cycles == 2
    assert "fetch-policy full set failed" in caplog.text
