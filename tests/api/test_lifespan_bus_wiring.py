"""The lifespan's bus wiring — publisher and consumer start conditions.

`consumer_enabled` is unit-tested in isolation, but the gate it feeds is the
safety control (`AGENTS.md`, "Four variables carry safety rules"), and an
untested safety control is an assertion about behaviour rather than a guarantee
of it (CR round 1, finding 8).

Covers:
1. No `ARCHIVER_REDIS_URL` → neither publisher nor consumer
2. Redis but no gate → publisher runs, consumer does not
3. Redis + gate → both run
4. Gate set but Redis absent → still no consumer (the gate is not its own switch)
5. Both tasks stop on shutdown
6. A consumer that cannot start leaves the publisher running
7. The registry-snapshot task starts and stops with the publisher, and its
   task/trigger handles are nulled on the dormant path (archiver#141)
8. The client is built with its connection policy, not bare (archiver#193)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from co_core.pure.adapters.bus.streams import CONTENT_REPLICATE
from fakeredis import aioredis as fakeredis_aio
from redis.exceptions import ConnectionError as RedisConnectionError

from src.api.main import app, lifespan
from src.core.changes import bus_client
from src.core.changes.outbox_prune import DEFAULT_RETENTION_DAYS

FAKE_REDIS_URL = "redis://localhost:6379/15"


@pytest.fixture
def bus_client_calls():
    """Make the lifespan's ``from_url`` hand back a FakeRedis, recording the call.

    **Patched where the call is, not where the name used to be** (CR finding 2).
    The lifespan builds its client through ``bus_client.build_bus_client`` since
    archiver#193 Phase 1, so a patch aimed at ``src.api.main.RedisAsync`` named a
    path the code no longer takes. It kept working only because ``patch`` mutates
    the attribute on the shared ``redis.asyncio.Redis`` class, which every module
    sees - so the target string was documentation that had gone quietly wrong,
    and the day ``bus_client`` imported ``Redis`` some other way, eighteen tests
    would have started reaching for a real broker. On this VM that is the
    production one.

    **Yields the recorded ``kwargs`` of each call, not the clients** - hence the
    name (CR round 2, finding 14). It was ``bus_client_calls`` while it
    yielded a client list nothing read; once round 1 made the connection policy
    assertable, the old name promised the wrong thing.
    """
    calls: list[dict] = []

    def _from_url(*_args, **kwargs):
        calls.append(kwargs)
        return fakeredis_aio.FakeRedis()

    with patch("src.core.changes.bus_client.RedisAsync.from_url", side_effect=_from_url):
        yield calls


@pytest.fixture
def bus_env(monkeypatch):
    """Start from a known-clean bus environment for each case."""
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    monkeypatch.delenv("ARCHIVER_BUS_CONSUMER", raising=False)
    return monkeypatch


@pytest.mark.asyncio
async def test_no_redis_url_starts_neither(bus_env, test_engine):
    async with lifespan(app):
        assert app.state.redis_client is None
        assert app.state.revisions_consumer_task is None
        # Dormant nulls both snapshot handles too — the republish route's 409
        # hangs off registry_snapshot_trigger being None (CR round 3, #12).
        assert app.state.registry_snapshot_task is None
        assert app.state.registry_snapshot_trigger is None


@pytest.mark.asyncio
async def test_redis_without_the_gate_starts_publisher_only(bus_env, bus_client_calls, test_engine):
    """Presence of a Redis URL is not authority to join a production group."""
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        assert app.state.redis_client is not None
        assert app.state.publisher_task is not None
        assert app.state.revisions_consumer_task is None
        # The snapshot task rides the publisher's gate, not the consumer's.
        assert app.state.registry_snapshot_task is not None
        assert not app.state.registry_snapshot_task.done()
        assert app.state.registry_snapshot_trigger is not None


@pytest.mark.asyncio
async def test_gate_without_redis_starts_neither(bus_env, test_engine):
    """The gate is a second condition, not an alternative one."""
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    async with lifespan(app):
        assert app.state.redis_client is None
        assert app.state.revisions_consumer_task is None


@pytest.mark.asyncio
async def test_redis_and_gate_start_both(bus_env, bus_client_calls, test_engine):
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    async with lifespan(app):
        assert app.state.publisher_task is not None
        assert app.state.revisions_consumer_task is not None
        assert not app.state.revisions_consumer_task.done()


@pytest.mark.asyncio
async def test_both_tasks_stop_on_shutdown(bus_env, bus_client_calls, test_engine):
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    async with lifespan(app):
        publisher_task = app.state.publisher_task
        consumer_task = app.state.revisions_consumer_task
        snapshot_task = app.state.registry_snapshot_task

    assert publisher_task.done()
    assert consumer_task.done()
    assert snapshot_task.done()


@pytest.mark.asyncio
async def test_consumer_failure_leaves_the_publisher_running(
    bus_env, bus_client_calls, test_engine
):
    """The two are gated and constructed separately for exactly this reason."""
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    with patch(
        "src.core.changes.consumer.build_consumer", side_effect=RuntimeError("no consumer for you")
    ):
        async with lifespan(app):
            assert app.state.publisher_task is not None
            assert not app.state.publisher_task.done()
            assert app.state.revisions_consumer_task is None


@pytest.mark.asyncio
async def test_watch_status_tail_runs_without_the_gate(bus_env, bus_client_calls, test_engine):
    """The tail is gated on the Redis URL alone (archiver#151): groupless, it
    removes nothing from a production PEL, so ``ARCHIVER_BUS_CONSUMER`` —
    whose whole point is group membership — deliberately does not apply."""
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        assert app.state.watch_status_task is not None
        assert not app.state.watch_status_task.done()
        assert app.state.revisions_consumer_task is None  # the gate still holds there


@pytest.mark.asyncio
async def test_watch_status_tail_dormant_without_redis(bus_env, test_engine):
    async with lifespan(app):
        assert app.state.watch_status_task is None


@pytest.mark.asyncio
async def test_watch_status_tail_stops_on_shutdown(bus_env, bus_client_calls, test_engine):
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        tail_task = app.state.watch_status_task

    assert tail_task.done()


@pytest.mark.asyncio
async def test_watch_status_failure_leaves_other_bus_tasks_running(
    bus_env, bus_client_calls, test_engine
):
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    with patch(
        "src.core.changes.watch_status_consumer.resolve_start_id",
        side_effect=RuntimeError("no cursor for you"),
    ):
        async with lifespan(app):
            assert app.state.publisher_task is not None
            assert not app.state.publisher_task.done()
            assert app.state.watch_status_task is None


@pytest.mark.asyncio
async def test_command_stream_is_carved_out_of_the_trim_loop(
    bus_env, bus_client_calls, test_engine
):
    """content.replicate must never be XTRIMmed (archiver#169).

    The drain loop caps every topic it publishes to, which is right for a fact
    stream Archiver owns and wrong for a *command* stream with a competing
    consumer group: trimming it deletes commands nobody delivered and orphans
    the PEL entries pointing at them. Retention on a command stream belongs to
    the consumer's progress, not the producer's cap.
    """
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    with patch("src.core.changes.publisher.run", side_effect=_capture):
        async with lifespan(app):
            pass

    assert CONTENT_REPLICATE in captured["no_trim_topics"]
    assert "info.registry" in captured["no_trim_topics"]


@pytest.mark.asyncio
async def test_artifacts_consumer_and_reaper_start_behind_the_gate(
    bus_env, bus_client_calls, test_engine
):
    """Same gate as the revisions consumer: joining a group removes messages
    from it, and the reaper closes the same commands that consumer would."""
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    async with lifespan(app):
        assert app.state.artifacts_consumer_task is not None
        assert app.state.replication_reaper_task is not None


@pytest.mark.asyncio
async def test_redis_without_the_gate_starts_neither_artifacts_nor_reaper(
    bus_env, bus_client_calls, test_engine
):
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        assert app.state.artifacts_consumer_task is None
        assert app.state.replication_reaper_task is None


@pytest.mark.asyncio
async def test_no_redis_url_nulls_every_handle(bus_env, test_engine):
    """A dormant path nulls every handle, so a stale value from a previous
    lifespan cannot satisfy an assertion (CR round 2, finding 15).

    **Poisons the handles first** (CR round 4, finding 23). ``app`` is a
    module-level singleton, so ``app.state`` outlives any one lifespan; asserting
    ``is None`` against state nothing ever set passes for the wrong reason and
    proves nothing about the nulling. Seeding a sentinel is what makes each
    assertion a statement about *this* lifespan.

    ``bus_reachability_task`` joins them here because it is now read by two
    tests below, which makes it exactly the kind of handle finding 15 was about:
    left stale, ``await app.state.bus_reachability_task`` would await a previous
    test's completed task and pass.
    """
    for handle in (
        "artifacts_consumer_task",
        "replication_reaper_task",
        "bus_reachability_task",
    ):
        setattr(app.state, handle, "stale-from-a-previous-lifespan")

    async with lifespan(app):
        assert app.state.artifacts_consumer_task is None
        assert app.state.replication_reaper_task is None
        assert app.state.bus_reachability_task is None


@pytest.mark.asyncio
async def test_reaper_runs_without_a_redis_url(bus_env, test_engine):
    """The reaper touches no broker (CR #22).

    It is a database-only safety net, and the case where the bus is
    misconfigured is arguably when stale `requested` rows are most likely — so
    its availability must not depend on ARCHIVER_REDIS_URL.
    """
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    async with lifespan(app):
        assert app.state.redis_client is None
        assert app.state.replication_reaper_task is not None


@pytest.mark.asyncio
async def test_reaper_stays_gated_on_the_consumer_flag(bus_env, test_engine):
    """Two sweepers would race to close the same commands."""
    async with lifespan(app):
        assert app.state.replication_reaper_task is None


@pytest.mark.asyncio
async def test_publisher_carries_the_resolved_retention_window(
    bus_env, bus_client_calls, test_engine
):
    """The archiver#189 pruner rides the drain loop, so the knob has to reach
    ``publisher.run``. Unset means the default window, not disabled - an
    unbounded outbox is the failure mode this exists to close."""
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.delenv("ARCHIVER_OUTBOX_RETENTION_DAYS", raising=False)
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    with patch("src.core.changes.publisher.run", side_effect=_capture):
        async with lifespan(app):
            pass

    assert captured["retention_days"] == DEFAULT_RETENTION_DAYS


@pytest.mark.asyncio
async def test_retention_knob_can_disable_the_pruner(bus_env, bus_client_calls, test_engine):
    """An operator holding rows for a forensic window keeps the publisher."""
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.setenv("ARCHIVER_OUTBOX_RETENTION_DAYS", "0")
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    with patch("src.core.changes.publisher.run", side_effect=_capture):
        async with lifespan(app):
            pass

    assert captured["retention_days"] is None


@pytest.mark.asyncio
async def test_lifespan_builds_its_client_with_the_connection_policy(
    bus_env, bus_client_calls, test_engine
):
    """The policy must reach the real client, not just exist in a module.

    CR finding 1. Every other test here asserts which *tasks* start; none
    asserted how the client they share is *built*. Reverting
    ``bus_client.build_bus_client(redis_url)`` to a bare
    ``RedisAsync.from_url(redis_url)`` left 284 tests green - the whole of
    archiver#193 Phase 1 could be undone without a single failure, which is the
    same defect class as archiver#194's CR round 2 (a guard that reads as
    coverage and cannot fail).

    This is the seam that matters: the module is thoroughly tested in isolation,
    so the only thing left to get wrong is whether production goes through it.
    """
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        pass

    assert bus_client_calls, "the lifespan never built a bus client"
    kwargs = bus_client_calls[0]
    assert kwargs["socket_timeout"] == bus_client.SOCKET_TIMEOUT_SECONDS
    assert kwargs["socket_connect_timeout"] == bus_client.SOCKET_CONNECT_TIMEOUT_SECONDS
    assert kwargs["health_check_interval"] == bus_client.HEALTH_CHECK_INTERVAL_SECONDS
    # redis-py exposes no public accessor for either, so both this file and
    # tests/core/changes/test_bus_client.py read the privates (CR round 2,
    # finding 15). A rename upstream breaks two files, not one.
    assert kwargs["retry"]._retries == bus_client.BUS_RETRIES


@pytest.mark.asyncio
async def test_lifespan_stays_dormant_without_a_url_and_builds_no_client(
    bus_env, bus_client_calls, test_engine
):
    """Dormancy must not construct a client pointed at the default host.

    ``build_bus_client`` refuses an empty URL, but the branch that decides never
    to call it is the lifespan's. Worth pinning from this side too: on the shared
    VM the default host is the production broker, so the cost of the guard being
    the *other* function's job is not recoverable.
    """
    async with lifespan(app):
        pass

    assert bus_client_calls == []


@pytest.mark.asyncio
async def test_client_is_closed_even_when_publisher_init_fails(bus_env, test_engine, monkeypatch):
    """A failure partway through bus init must still close the client.

    Deliberately does **not** take ``bus_client_calls``: it patches the same
    ``from_url`` itself, and stacking ``monkeypatch`` on top of that fixture's
    ``patch`` leaves the mock installed for the rest of the session, because the
    two teardowns are not guaranteed to unwind in the order that requires. That
    escaped a targeted run of this file and only surfaced in the full suite, as
    an unrelated failure in ``test_bus_client.py``.

    CR finding 7. The ``except`` sets ``redis_client = None`` to mean "no
    publisher", and the shutdown close used to key off that same name - so this
    path leaked. It was invisible while ``from_url`` was lazy and nothing had
    connected; the reachability PING added in Phase 1 means a connection may now
    be open when init fails, which is what turns a tidy-looking alias into a real
    leak.
    """
    closed: list[bool] = []

    class _TrackingRedis(fakeredis_aio.FakeRedis):
        async def aclose(self, *a, **k):
            closed.append(True)
            return await super().aclose(*a, **k)

    monkeypatch.setattr(
        "src.core.changes.bus_client.RedisAsync.from_url",
        lambda *_a, **_k: _TrackingRedis(),
    )
    # Fail *after* the client exists, which is the window that leaked.
    monkeypatch.setattr(
        "src.core.changes.publisher.resolve_stream_maxlen",
        lambda _v: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        # Init failed, so the publisher is disowned...
        assert app.state.publisher_task is None

    # ...but the client it had already built is still closed.
    assert closed == [True]


@pytest.mark.asyncio
async def test_unreachable_broker_is_reported_at_error_by_the_lifespan(
    bus_env, test_engine, monkeypatch
):
    """A configured-but-unreachable broker must be loud, end to end.

    CR round 2, finding 11. Round 1 closed the *client policy* half of this
    wiring and left this half open: deleting the
    ``asyncio.create_task(probe_bus_reachable(...))`` line left 592 tests green.
    ``probe_bus_reachable`` is exhaustively covered in isolation, and nothing
    asserted the lifespan ever calls it - so the epic's item 3 could be removed
    whole, and the only symptom would be the silence it exists to prevent.

    Drives it from the outside for that reason: a broker whose ``ping`` fails,
    through the real lifespan, must produce the ERROR line. That covers the
    wiring and the contract together, which testing the function alone cannot.
    """
    errors: list[dict] = []
    monkeypatch.setattr(
        bus_client.logger,
        "error",
        lambda _msg, *a, **k: errors.append(k.get("extra", {})),
    )

    class _UnreachableRedis(fakeredis_aio.FakeRedis):
        async def ping(self, *a, **k):
            raise RedisConnectionError("Error 111 connecting to broker:6379.")

    monkeypatch.setattr(
        "src.core.changes.bus_client.RedisAsync.from_url",
        lambda *_a, **_k: _UnreachableRedis(),
    )
    bus_env.setenv("ARCHIVER_REDIS_URL", "redis://:hunter2@broker:6379/0")

    async with lifespan(app):
        # Await the handle rather than yielding and hoping (CR round 3,
        # finding 18). ``asyncio.sleep(0)`` happened to suffice only because
        # this double's ``ping`` raises without suspending.
        await app.state.bus_reachability_task

    assert len(errors) == 1, "an unreachable broker produced no ERROR line"
    # Redacted at the boundary the operator actually reads (journald).
    assert errors[0]["redis_url"] == "redis://:***@broker:6379/0"
    assert "hunter2" not in repr(errors)


@pytest.mark.asyncio
async def test_reachable_broker_is_reported_at_info_and_not_at_error(
    bus_env, test_engine, monkeypatch
):
    """The other edge: a healthy broker reports success, and does not cry wolf.

    Asserts the INFO line **positively** (CR round 3, finding 17). The first
    version only asserted the absence of an ERROR, which a deleted probe
    satisfies perfectly - verified: with the ``create_task`` line removed, this
    test passed while its failure-side twin failed. An absence is not evidence
    the thing ran, and it was added precisely to be the evidence that the ERROR
    assertion is not satisfiable by a logger that fires unconditionally.
    """
    errors: list[dict] = []
    infos: list[dict] = []
    monkeypatch.setattr(bus_client.logger, "error", lambda *a, **k: errors.append(k))
    monkeypatch.setattr(
        bus_client.logger, "info", lambda _m, *a, **k: infos.append(k.get("extra", {}))
    )
    monkeypatch.setattr(
        "src.core.changes.bus_client.RedisAsync.from_url",
        lambda *_a, **_k: fakeredis_aio.FakeRedis(),
    )
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        assert await app.state.bus_reachability_task is True

    reachable = [i for i in infos if "rtt_ms" in i]
    assert len(reachable) == 1, "a reachable broker produced no INFO line"
    assert reachable[0]["redis_url"] == FAKE_REDIS_URL
    assert errors == []


@pytest.mark.asyncio
async def test_publisher_init_failure_disowns_the_reachability_handle(
    bus_env, test_engine, monkeypatch
):
    """The disown path nulls the probe handle like every other one.

    CR round 4, finding 23: both nullings of this handle were unguarded -
    removing them left 324 tests green. Poisoned first for the reason given on
    the dormant test.

    The *task* is deliberately left running: a broker that is down is worth
    reporting whether or not publisher init also failed, and the two have no
    causal link. Only the handle is disowned, matching its siblings on this path.
    """
    app.state.bus_reachability_task = "stale-from-a-previous-lifespan"

    monkeypatch.setattr(
        "src.core.changes.bus_client.RedisAsync.from_url",
        lambda *_a, **_k: fakeredis_aio.FakeRedis(),
    )
    monkeypatch.setattr(
        "src.core.changes.publisher.resolve_stream_maxlen",
        lambda _v: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        assert app.state.publisher_task is None
        assert app.state.bus_reachability_task is None
