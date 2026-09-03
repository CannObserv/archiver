"""Tests for the broker-side bus-health probes (archiver#130).

The pure ``evaluate_*`` functions carry the thresholds; the ``collect_*``
functions are exercised against fakeredis so the Redis command surface
(XLEN / XINFO STREAM / XPENDING / SCAN) is real, not mocked. The two-tick
pending rule and the state file that carries it between oneshot runs get
their own coverage because the timer is stateless without them.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from co_core.pure.adapters.bus.streams import (
    CONTENT_ARTIFACTS,
    CONTENT_BLOBS,
    CONTENT_FETCH,
    CONTENT_FETCH_POLICY,
    CONTENT_REPLICATE,
    CONTENT_REVISIONS,
    INFO_CHANGES,
    INFO_REGISTRY,
    INFO_WATCH_STATUS,
    dlq_name,
    stream_kind,
)
from fakeredis import aioredis as fakeredis_aio

from src.core import bus_health
from src.core.bus_health import (
    DISK_WARN_MIN_FREE_BYTES,
    FACT_WARN_LENGTH,
    STREAM_CHECKS,
    StreamCheck,
    collect_broker_findings,
    evaluate_disk,
    evaluate_memory,
    evaluate_outbox,
    evaluate_pending,
    evaluate_stream,
    load_state,
    save_state,
    with_margin,
)
from src.core.changes.consumer import CONSUMER_GROUP as REVISIONS_GROUP
from src.core.changes.outbox_stats import OutboxStats
from src.core.changes.publisher import DEFAULT_STREAM_MAXLEN
from src.core.changes.registry_snapshot import DEFAULT_REGISTRY_STREAM_MAXLEN


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


# --- memory ---


def test_memory_healthy_below_fraction() -> None:
    assert evaluate_memory(used_memory=100, maxmemory=1000) == []


def test_memory_warns_at_fraction() -> None:
    findings = evaluate_memory(used_memory=750, maxmemory=1000)
    assert len(findings) == 1
    assert findings[0].check == "memory"


def test_memory_warns_when_maxmemory_unset() -> None:
    """maxmemory 0 makes noeviction inert (archiver#128) - that is a finding."""
    findings = evaluate_memory(used_memory=100, maxmemory=0)
    assert len(findings) == 1
    assert "maxmemory" in findings[0].message


# --- disk ---


def test_disk_healthy() -> None:
    total = 100 * 1024**3
    assert evaluate_disk(total=total, free=total // 2) == []


def test_disk_warns_at_used_fraction() -> None:
    total = 100 * 1024**3
    findings = evaluate_disk(total=total, free=total // 20)  # 95% used
    assert any(f.check == "disk" for f in findings)


def test_disk_warns_below_min_free() -> None:
    """Small disks: an absolute floor fires even under the fraction."""
    total = 10 * 1024**3
    free = DISK_WARN_MIN_FREE_BYTES - 1  # < 2 GiB free but only 80% used
    findings = evaluate_disk(total=total, free=free)
    assert any(f.check == "disk" for f in findings)


# --- stream length + last-entry age ---

_CHECK = StreamCheck(
    topic="t",
    warn_length=100,
    warn_last_entry_age_seconds=900.0,
)


def test_stream_healthy() -> None:
    now_ms = 10_000_000
    assert evaluate_stream(_CHECK, length=50, last_entry_ms=now_ms, now_ms=now_ms) == []


def test_stream_warns_over_length() -> None:
    now_ms = 10_000_000
    findings = evaluate_stream(_CHECK, length=101, last_entry_ms=now_ms, now_ms=now_ms)
    assert [f.check for f in findings] == ["stream-length"]


def test_stream_warns_on_stale_last_entry() -> None:
    now_ms = 10_000_000
    stale = now_ms - 901_000
    findings = evaluate_stream(_CHECK, length=50, last_entry_ms=stale, now_ms=now_ms)
    assert [f.check for f in findings] == ["stream-age"]


def test_stream_empty_skips_age() -> None:
    """A never-written or empty stream has no last entry to age-check; an empty
    registry publishes nothing by design (the corpus-size guard, #147)."""
    findings = evaluate_stream(_CHECK, length=0, last_entry_ms=None, now_ms=10_000_000)
    assert findings == []


def test_stream_without_age_threshold_skips_age() -> None:
    check = StreamCheck(topic="t", warn_length=100)
    findings = evaluate_stream(check, length=50, last_entry_ms=0, now_ms=10_000_000)
    assert findings == []


# --- two-tick pending ---


def test_pending_first_tick_is_grace() -> None:
    check = StreamCheck(topic="t", pending_group="g")
    assert evaluate_pending(check, pending_now=5, pending_prev=0) == []


def test_pending_two_consecutive_ticks_warn() -> None:
    check = StreamCheck(topic="t", pending_group="g")
    findings = evaluate_pending(check, pending_now=5, pending_prev=3)
    assert [f.check for f in findings] == ["pending"]


def test_pending_recovered_is_healthy() -> None:
    check = StreamCheck(topic="t", pending_group="g")
    assert evaluate_pending(check, pending_now=0, pending_prev=5) == []


def test_pending_message_names_no_specific_stream() -> None:
    """CR round 1, finding 2. The check runs for both archiver-owned groups, so
    a wedged artifacts consumer must not be reported as lost revisions - wrong
    stream, wrong remedy. The subject already carries topic/group."""
    check = _check_for(CONTENT_ARTIFACTS)
    (finding,) = evaluate_pending(check, pending_now=5, pending_prev=3)
    assert finding.subject == f"{CONTENT_ARTIFACTS}/archiver.artifacts"
    assert "revision" not in finding.message.lower()


# --- outbox ---


def test_outbox_healthy() -> None:
    stats = OutboxStats(
        unpublished_count=3,
        oldest_unpublished_age_seconds=1.0,
        dead_lettered_count=0,
    )
    assert evaluate_outbox(stats) == []


def test_outbox_warns_on_stale_backlog() -> None:
    stats = OutboxStats(
        unpublished_count=3,
        oldest_unpublished_age_seconds=301.0,
        dead_lettered_count=0,
    )
    findings = evaluate_outbox(stats)
    assert [f.check for f in findings] == ["outbox"]


def test_outbox_warns_on_dead_lettered() -> None:
    stats = OutboxStats(
        unpublished_count=0,
        oldest_unpublished_age_seconds=None,
        dead_lettered_count=1,
    )
    findings = evaluate_outbox(stats)
    assert [f.check for f in findings] == ["outbox"]


# --- inventory ---


def test_inventory_never_touches_content_blobs() -> None:
    """The content.blobs role boundary is unqualified - no read-only exception
    (CLAUDE.md). The probe list must never grow a row for it."""
    assert not any(c.topic == "content.blobs" for c in STREAM_CHECKS)


def test_inventory_covers_archiver_owned_groups() -> None:
    groups = {c.pending_group for c in STREAM_CHECKS if c.pending_group}
    assert groups == {"archiver.revisions", "archiver.artifacts"}


def _check_for(topic: str) -> StreamCheck:
    return next(c for c in STREAM_CHECKS if c.topic == topic)


def test_registry_threshold_tracks_its_own_producer_cap() -> None:
    """CR round 1, finding 1. info.registry is excluded from the operator-side
    XTRIM loop and capped on publish at DEFAULT_REGISTRY_STREAM_MAXLEN instead,
    so reusing the fact-stream threshold would let it reach 2.2x its cap before
    warning - defeating the "a breach means the trim contract broke" contract
    for the one stream whose retention floor is a consumer boot contract
    (#141)."""
    assert _check_for(INFO_REGISTRY).warn_length == with_margin(DEFAULT_REGISTRY_STREAM_MAXLEN)
    assert _check_for(INFO_REGISTRY).warn_length < FACT_WARN_LENGTH


def test_fact_stream_threshold_tracks_the_operator_xtrim_cap() -> None:
    """Derived, not copied: a change to the XTRIM default moves the threshold
    with it rather than silently leaving a stale literal here."""
    assert _check_for(INFO_CHANGES).warn_length == with_margin(DEFAULT_STREAM_MAXLEN)
    assert FACT_WARN_LENGTH > DEFAULT_STREAM_MAXLEN


def test_never_trimmed_stream_does_not_claim_a_broken_cap() -> None:
    """CR round 1, finding 5. content.replicate is carved out of the trim set
    (capping a command stream orphans PEL entries), so it grows monotonically;
    a breach there is a volume milestone, not a retention failure."""
    check = _check_for(CONTENT_REPLICATE)
    assert check.never_trimmed
    (finding,) = evaluate_stream(check, length=check.warn_length + 1, last_entry_ms=None, now_ms=0)
    assert "never trimmed" in finding.message
    assert "not being applied" not in finding.message


def test_trimmed_stream_still_names_the_broken_cap() -> None:
    check = _check_for(INFO_CHANGES)
    (finding,) = evaluate_stream(check, length=check.warn_length + 1, last_entry_ms=None, now_ms=0)
    assert "never trimmed" not in finding.message


# --- collectors against fakeredis ---


async def test_collect_reports_stale_lww_stream(fake_redis) -> None:
    """An entry older than the age threshold on a groupless LWW stream warns."""
    await fake_redis.xadd(CONTENT_FETCH_POLICY, {"k": "v"}, id="1000-0")
    findings, _ = await collect_broker_findings(fake_redis, previous_pending={})
    assert any(f.check == "stream-age" and f.subject == CONTENT_FETCH_POLICY for f in findings)


async def test_collect_reports_nonempty_dlq(fake_redis) -> None:
    """Resting state is depth 0 on every *.dlq key (archiver#162)."""
    await fake_redis.xadd("content.revisions.dlq", {"k": "v"})
    findings, _ = await collect_broker_findings(fake_redis, previous_pending={})
    assert any(f.check == "dlq" and f.subject == "content.revisions.dlq" for f in findings)


async def test_collect_missing_group_is_a_finding(fake_redis) -> None:
    """A consumer group that should exist but does not means the consumer never
    provisioned - silent, so the probe must say it."""
    await fake_redis.xadd(CONTENT_REVISIONS, {"k": "v"})
    findings, _ = await collect_broker_findings(fake_redis, previous_pending={})
    assert any(f.check == "group-missing" and f.subject == CONTENT_REVISIONS for f in findings)


async def test_collect_pending_carries_state_between_ticks(fake_redis) -> None:
    await fake_redis.xadd(CONTENT_REVISIONS, {"k": "v"})
    await fake_redis.xgroup_create(CONTENT_REVISIONS, "archiver.revisions", id="0")
    await fake_redis.xreadgroup(
        "archiver.revisions", "c1", {CONTENT_REVISIONS: ">"}, count=10
    )  # deliver without ack -> pending=1

    findings, pending = await collect_broker_findings(fake_redis, previous_pending={})
    key = f"{CONTENT_REVISIONS}/archiver.revisions"
    assert pending[key] == 1
    assert not any(f.check == "pending" for f in findings)  # first tick: grace

    findings, _ = await collect_broker_findings(fake_redis, previous_pending=pending)
    assert any(f.check == "pending" for f in findings)  # second tick: warn


async def test_collect_fresh_registry_is_healthy(fake_redis) -> None:
    findings, _ = await collect_broker_findings(fake_redis, previous_pending={})
    assert not any(f.subject == INFO_REGISTRY for f in findings)


async def test_collect_unreachable_broker_is_a_finding() -> None:
    class DownRedis:
        def __getattr__(self, name):
            async def _raise(*a, **kw):
                raise ConnectionError("refused")

            return _raise

    findings, pending = await collect_broker_findings(DownRedis(), previous_pending={"x": 1})
    assert [f.check for f in findings] == ["broker"]
    assert pending == {"x": 1}  # state preserved so the grace tick is not reset


# --- group lag for the dashboard panel (archiver#147) ---


def _lag_for(lags: list[bus_health.GroupLag], topic: str) -> bus_health.GroupLag:
    (lag,) = [item for item in lags if item.topic == topic]
    return lag


async def test_group_lag_covers_exactly_the_archiver_owned_groups(fake_redis) -> None:
    """The panel answers for the groups Archiver runs consumers for, and only
    those - the same set STREAM_CHECKS names. A downstream service's group lag
    is its own alerting problem (see the module docstring)."""
    lags = await bus_health.collect_group_lag(fake_redis)
    assert {(lag.topic, lag.group) for lag in lags} == {
        (check.topic, check.pending_group)
        for check in STREAM_CHECKS
        if check.pending_group is not None
    }


async def test_group_lag_reports_pending_and_dlq_depth(fake_redis) -> None:
    """Both numbers issue #147 asks the panel for: XPENDING on the group and
    XLEN on its DLQ."""
    await fake_redis.xadd(CONTENT_REVISIONS, {"k": "v"})
    await fake_redis.xgroup_create(CONTENT_REVISIONS, REVISIONS_GROUP, id="0")
    await fake_redis.xreadgroup(
        REVISIONS_GROUP, "c1", {CONTENT_REVISIONS: ">"}, count=10
    )  # delivered, unacked -> pending=1
    await fake_redis.xadd(dlq_name(CONTENT_REVISIONS), {"k": "v"})

    lag = _lag_for(await bus_health.collect_group_lag(fake_redis), CONTENT_REVISIONS)

    assert lag.pending == 1
    assert lag.dlq_depth == 1


async def test_group_lag_distinguishes_a_missing_group_from_zero(fake_redis) -> None:
    """``pending is None`` means the consumer never provisioned its group. The
    panel must not render that as a healthy zero - it is the silent state #147
    exists to stop showing green."""
    lag = _lag_for(await bus_health.collect_group_lag(fake_redis), CONTENT_REVISIONS)

    assert lag.pending is None
    assert lag.dlq_depth == 0


async def test_group_lag_propagates_an_unreachable_broker() -> None:
    """Unlike the timer's collector, this one does not turn an outage into a
    finding: the caller is a request handler that must distinguish "measured
    zero" from "could not measure" and badge them differently."""

    class DownRedis:
        def __getattr__(self, name):
            async def _raise(*a, **kw):
                raise ConnectionError("refused")

            return _raise

    with pytest.raises(ConnectionError):
        await bus_health.collect_group_lag(DownRedis())


async def test_collect_tolerates_a_non_stream_dlq_key(fake_redis) -> None:
    """CR round 1, finding 7. A stray non-stream key named *.dlq must not raise
    WRONGTYPE out of the DLQ scan - that would surface as "broker unreachable"
    and discard every other finding on the tick."""
    await fake_redis.set("stray.dlq", "not-a-stream")
    await fake_redis.xadd("content.fetch.dlq", {"k": "v"})

    findings, _ = await collect_broker_findings(fake_redis, previous_pending={})

    assert not any(f.check == "broker" for f in findings)
    assert [f.subject for f in findings if f.check == "dlq"] == ["content.fetch.dlq"]


# --- state file ---


def test_state_round_trip(tmp_path) -> None:
    path = tmp_path / "state.json"
    save_state(path, {"a/b": 3})
    assert load_state(path) == {"a/b": 3}


def test_state_missing_file_is_empty(tmp_path) -> None:
    assert load_state(tmp_path / "absent.json") == {}


def test_state_corrupt_file_is_empty(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not json{")
    assert load_state(path) == {}


# --- logging surface ---


def _healthy_disk(path: str) -> tuple[int, int, int]:
    total = 100 * 1024**3
    return total, total // 2, total // 2


async def test_run_once_logs_each_finding_at_warning(fake_redis, tmp_path, monkeypatch) -> None:
    """Spies the module logger rather than using caplog: configure_logging()
    replaces root.handlers, which defeats pytest's capture handler."""
    await fake_redis.xadd("content.fetch.dlq", {"k": "v"})
    warning_spy, info_spy = MagicMock(), MagicMock()
    monkeypatch.setattr(bus_health.logger, "warning", warning_spy)
    monkeypatch.setattr(bus_health.logger, "info", info_spy)

    findings = await bus_health.run_once(
        fake_redis,
        session_factory=None,
        state_path=tmp_path / "state.json",
        disk_usage=_healthy_disk,
    )

    assert findings
    # One line per finding, plus the summary line which escalates to WARNING
    # while any finding exists (same persistent-visibility contract as #112).
    assert warning_spy.call_count == len(findings) + 1
    info_spy.assert_not_called()


async def test_run_once_healthy_logs_info_summary(fake_redis, tmp_path, monkeypatch) -> None:
    warning_spy, info_spy = MagicMock(), MagicMock()
    monkeypatch.setattr(bus_health.logger, "warning", warning_spy)
    monkeypatch.setattr(bus_health.logger, "info", info_spy)

    findings = await bus_health.run_once(
        fake_redis,
        session_factory=None,
        state_path=tmp_path / "state.json",
        disk_usage=_healthy_disk,
    )

    assert findings == []
    warning_spy.assert_not_called()
    info_spy.assert_called_once()
    assert info_spy.call_args.kwargs["extra"]["finding_count"] == 0


# --- timer entrypoint ---


@pytest.fixture
def stub_main_deps(monkeypatch, tmp_path):
    """Neutralise everything main() touches outside the probe itself, and hand
    back the spies the entrypoint contracts are asserted on."""
    monkeypatch.setenv("ARCHIVER_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(bus_health, "configure_logging", lambda: None)
    monkeypatch.setattr(bus_health, "get_database_url", lambda: "postgresql://db/x")
    monkeypatch.setattr(bus_health, "assert_production_db_allowed", lambda *a, **kw: None)
    monkeypatch.setattr(bus_health, "get_session_factory", lambda: None)

    client = AsyncMock()
    from_url = MagicMock(return_value=client)
    monkeypatch.setattr(bus_health.Redis, "from_url", from_url)

    engine = AsyncMock()
    monkeypatch.setattr(bus_health, "get_engine", MagicMock(return_value=engine))

    async def _noop_run_once(*a, **kw):
        return []

    monkeypatch.setattr(bus_health, "run_once", _noop_run_once)
    return SimpleNamespace(
        from_url=from_url,
        client=client,
        engine=engine,
        state_file=tmp_path / "state.json",
    )


def test_main_bounds_the_redis_socket(stub_main_deps) -> None:
    """CR round 1, finding 3. A hung (not refusing) broker would otherwise block
    past systemd's TimeoutStartSec and fail the unit, instead of producing the
    WARN-only "broker unreachable" finding this module promises - the probe's
    contract breaking in exactly the degraded state it exists to observe."""
    assert bus_health.main(["--state-file", str(stub_main_deps.state_file)]) == 0

    kwargs = stub_main_deps.from_url.call_args.kwargs
    assert kwargs["socket_connect_timeout"] > 0
    assert kwargs["socket_timeout"] > 0


def test_main_releases_both_pools(stub_main_deps) -> None:
    """CR round 1, finding 6. The DB engine is disposed alongside the Redis
    client; an asyncpg pool reclaimed during loop teardown emits "Event loop is
    closed" noise into the journald stream this unit exists to keep clean."""
    assert bus_health.main(["--state-file", str(stub_main_deps.state_file)]) == 0

    stub_main_deps.client.aclose.assert_awaited_once()
    stub_main_deps.engine.dispose.assert_awaited_once()


def test_main_without_a_broker_url_is_dormant(stub_main_deps, monkeypatch) -> None:
    monkeypatch.delenv("ARCHIVER_REDIS_URL")
    assert bus_health.main(["--state-file", str(stub_main_deps.state_file)]) == 0
    stub_main_deps.from_url.assert_not_called()


async def test_run_once_persists_state(fake_redis, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    await bus_health.run_once(
        fake_redis,
        session_factory=None,
        state_path=state_path,
        disk_usage=_healthy_disk,
    )
    assert json.loads(state_path.read_text()) == {}


# --- stream-kind invariants (cannobserv#384, co-core >=0.13.1) --------------
#
# ``pending_group`` was a hand-kept field whose correctness rested on the
# author knowing the three-kind taxonomy. ``stream_kind`` makes that taxonomy
# machine-readable, so the rule "a config/state stream never carries a group"
# stops being a comment and becomes a constructor guard.


def test_stream_check_rejects_a_pending_group_on_a_config_state_stream() -> None:
    """A config/state stream must never carry a consumer group.

    A group there accumulates a PEL nothing drains: every worker needs every
    message, so nobody acks on behalf of the others. co-core states the rule;
    this makes STREAM_CHECKS unable to express a violation of it.
    """
    with pytest.raises(ValueError, match="config_state"):
        StreamCheck(INFO_REGISTRY, warn_length=10, pending_group="archiver.registry")


def test_stream_check_allows_a_pending_group_on_a_fact_stream() -> None:
    """The guard must not overreach: fact streams are exactly where groups live.

    The group name is deliberately *not* a conventional one. The guard keys on
    the topic's kind and must have no opinion about the group's spelling -
    asserting with ``archiver.revisions`` would leave both behaviours
    consistent with a pass.
    """
    check = StreamCheck(CONTENT_REVISIONS, warn_length=10, pending_group="not-a-convention")
    assert check.pending_group == "not-a-convention"


def test_stream_check_allows_a_pending_group_on_a_command_stream() -> None:
    """``command`` is the third kind, and it takes exactly one group."""
    check = StreamCheck(CONTENT_REPLICATE, warn_length=10, pending_group="replicator.replicate")
    assert check.pending_group == "replicator.replicate"


@pytest.mark.parametrize(
    "topic",
    [
        INFO_CHANGES,
        CONTENT_BLOBS,
        CONTENT_FETCH,
        CONTENT_REVISIONS,
        CONTENT_ARTIFACTS,
        CONTENT_REPLICATE,
        CONTENT_FETCH_POLICY,
        INFO_REGISTRY,
        INFO_WATCH_STATUS,
    ],
)
def test_every_canonical_stream_constant_is_classifiable(topic: str) -> None:
    """``StreamCheck``'s guard fails *open* on a ``ValueError`` from ``stream_kind``.

    That swallow is unavoidable - co-core publishes no public set of canonical
    topics to test membership against - so its safety rests on ``ValueError``
    meaning "not canonical" and nothing else. If a future co-core stopped
    classifying a constant archiver uses, the guard would quietly stop guarding
    that stream and no other test would notice. This is the tripwire.
    """
    assert stream_kind(topic) in ("command", "fact", "config_state")


@pytest.mark.parametrize("check", STREAM_CHECKS, ids=lambda c: c.topic)
def test_no_config_state_check_carries_a_group(check: StreamCheck) -> None:
    """The live inventory obeys the rule the constructor now enforces."""
    if stream_kind(check.topic) == "config_state":
        assert check.pending_group is None, (
            f"{check.topic} is a config/state stream and must not have a consumer group"
        )
