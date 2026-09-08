"""Tests for archiver's bus-health surface.

Reduced to archiver's half by archiver#193 Phase 3. The broker-side probes -
memory, per-stream ``XLEN``, last-entry age, the two-tick ``XPENDING`` rule,
the DLQ sweep, and disk - moved to CannObserv/broker with the host they
measure (D6). What remains is what queries archiver's own database or serves
archiver's own dashboard.

The pure ``evaluate_outbox`` carries the thresholds; ``collect_group_lag`` is
exercised against fakeredis so the Redis command surface (XPENDING / XLEN) is
real, not mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, MagicMock

import pytest
from co_core.pure.adapters.bus.streams import (
    CONTENT_ARTIFACTS,
    CONTENT_REPLICATE,
    CONTENT_REVISIONS,
    INFO_REGISTRY,
    StreamKind,
    dlq_name,
    stream_kind,
)
from fakeredis import aioredis as fakeredis_aio

from src.core import bus_health
from src.core.bus_health import (
    OWNED_GROUPS,
    OwnedGroup,
    evaluate_outbox,
)
from src.core.changes.consumer import CONSUMER_GROUP as REVISIONS_GROUP
from src.core.changes.outbox_stats import OutboxStats


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


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


async def test_collect_outbox_findings_turns_a_db_failure_into_a_finding() -> None:
    """The probe's whole point is to keep reporting while something is down.
    A database that refuses is the finding, not an exception out of the tick."""

    def _explode():
        raise RuntimeError("connection refused")

    findings = await bus_health.collect_outbox_findings(_explode)
    assert [f.check for f in findings] == ["outbox"]
    assert "connection refused" in findings[0].message


# --- the owned-group inventory ---


def test_inventory_never_touches_content_blobs() -> None:
    """The content.blobs role boundary is unqualified - no read-only exception
    (CLAUDE.md). The list must never grow a row for it."""
    assert not any(g.topic == "content.blobs" for g in OWNED_GROUPS)


def test_inventory_covers_exactly_the_groups_archiver_consumes() -> None:
    """Every entry is a group archiver runs a consumer for. Unlike the probe
    this list was carved out of, it has no rows for streams archiver merely
    publishes to: those had length and age thresholds, which measure the
    broker's retention and moved to CannObserv/broker with it."""
    assert {(g.topic, g.group) for g in OWNED_GROUPS} == {
        (CONTENT_REVISIONS, "archiver.revisions"),
        (CONTENT_ARTIFACTS, "archiver.artifacts"),
    }


# --- group lag for the dashboard panel (archiver#147) ---


def _lag_for(lags: list[bus_health.GroupLag], topic: str) -> bus_health.GroupLag:
    (lag,) = [item for item in lags if item.topic == topic]
    return lag


async def test_group_lag_covers_exactly_the_archiver_owned_groups(fake_redis) -> None:
    """The panel answers for the groups Archiver runs consumers for, and only
    those - the same set OWNED_GROUPS names. A downstream service's group lag
    is its own alerting problem, and broker-wide symptoms are the broker
    repo's probe."""
    lags = await bus_health.collect_group_lag(fake_redis)
    assert {(lag.topic, lag.group) for lag in lags} == {(g.topic, g.group) for g in OWNED_GROUPS}


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
    """A broker outage is not folded into a finding here: the caller is a
    request handler that must distinguish "measured zero" from "could not
    measure" and badge them differently (#147)."""

    class DownRedis:
        def __getattr__(self, name):
            async def _raise(*a, **kw):
                raise ConnectionError("refused")

            return _raise

    with pytest.raises(ConnectionError):
        await bus_health.collect_group_lag(DownRedis())


# --- logging surface ---


async def test_run_once_logs_each_finding_at_warning(monkeypatch) -> None:
    """Spies the module logger rather than using caplog: configure_logging()
    replaces root.handlers, which defeats pytest's capture handler."""
    warning_spy, info_spy = MagicMock(), MagicMock()
    monkeypatch.setattr(bus_health.logger, "warning", warning_spy)
    monkeypatch.setattr(bus_health.logger, "info", info_spy)

    def _explode():
        raise RuntimeError("db down")

    findings = await bus_health.run_once(session_factory=_explode)

    assert findings
    # One line per finding, plus the summary line which escalates to WARNING
    # while any finding exists (same persistent-visibility contract as #112).
    assert warning_spy.call_count == len(findings) + 1
    info_spy.assert_not_called()


async def test_run_once_healthy_logs_info_summary(monkeypatch) -> None:
    warning_spy, info_spy = MagicMock(), MagicMock()
    monkeypatch.setattr(bus_health.logger, "warning", warning_spy)
    monkeypatch.setattr(bus_health.logger, "info", info_spy)
    monkeypatch.setattr(
        bus_health,
        "collect_outbox_findings",
        AsyncMock(return_value=[]),
    )

    findings = await bus_health.run_once(session_factory=MagicMock())

    assert findings == []
    warning_spy.assert_not_called()
    info_spy.assert_called_once()
    assert info_spy.call_args.kwargs["extra"]["finding_count"] == 0


# --- timer entrypoint ---


@pytest.fixture
def stub_main_deps(monkeypatch):
    """Neutralise everything main() touches outside the probe itself, and hand
    back the spies the entrypoint contracts are asserted on."""
    monkeypatch.setattr(bus_health, "configure_logging", lambda: None)
    monkeypatch.setattr(bus_health, "get_database_url", lambda: "postgresql://db/x")
    monkeypatch.setattr(bus_health, "assert_production_db_allowed", lambda *a, **kw: None)
    monkeypatch.setattr(bus_health, "get_session_factory", lambda: None)

    engine = AsyncMock()
    monkeypatch.setattr(bus_health, "get_engine", MagicMock(return_value=engine))

    async def _noop_run_once(*a, **kw):
        return []

    monkeypatch.setattr(bus_health, "run_once", _noop_run_once)
    return SimpleNamespace(engine=engine)


def test_main_releases_the_engine(stub_main_deps) -> None:
    """An asyncpg pool reclaimed during loop teardown emits "Event loop is
    closed" noise into the journald stream this unit exists to keep clean."""
    assert bus_health.main([]) == 0
    stub_main_deps.engine.dispose.assert_awaited_once()


def test_main_probes_even_with_no_broker_url(monkeypatch) -> None:
    """archiver#193 Phase 3, and the one behaviour this reduction is *for*.

    The timer used to probe the broker, so it returned early when
    ``ARCHIVER_REDIS_URL`` was unset - correct then, silent now. The broker is
    watched from its own node, and a bus-dormant archiver still has an outbox
    worth reporting on; a dormancy skip here would report nothing on exactly
    the host that most needs it.

    Asserted on ``run_once`` actually being reached rather than on ``main``
    returning 0, which it does either way.
    """
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    monkeypatch.setattr(bus_health, "configure_logging", lambda: None)
    monkeypatch.setattr(bus_health, "get_database_url", lambda: "postgresql://db/x")
    monkeypatch.setattr(bus_health, "assert_production_db_allowed", lambda *a, **kw: None)
    monkeypatch.setattr(bus_health, "get_session_factory", lambda: None)
    monkeypatch.setattr(bus_health, "get_engine", MagicMock(return_value=AsyncMock()))

    ran = MagicMock()

    async def _spy_run_once(**kwargs):
        ran(**kwargs)
        return []

    monkeypatch.setattr(bus_health, "run_once", _spy_run_once)

    assert bus_health.main([]) == 0
    ran.assert_called_once()


def test_main_still_gates_the_production_database(monkeypatch) -> None:
    """The reduced probe is *only* a database reader now, so the db_safety gate
    is the whole of its blast radius. It must still run, and must still be
    handed the flag from the unit rather than an env file."""
    seen: dict[str, object] = {}

    def _record(url, *, allow_flag):
        seen["url"] = url
        seen["allow_flag"] = allow_flag
        raise SystemExit(2)

    monkeypatch.setattr(bus_health, "configure_logging", lambda: None)
    monkeypatch.setattr(bus_health, "get_database_url", lambda: "postgresql://db/archiver")
    monkeypatch.setattr(bus_health, "assert_production_db_allowed", _record)
    monkeypatch.setenv("ARCHIVER_ALLOW_PRODUCTION_DB", "1")

    with pytest.raises(SystemExit):
        bus_health.main([])

    assert seen["url"] == "postgresql://db/archiver"
    assert seen["allow_flag"] == "1"


# --- stream-kind invariants (cannobserv#384, co-core >=0.13.1) --------------


def test_owned_group_rejects_a_config_state_stream() -> None:
    """A config/state stream must never carry a consumer group.

    A group there accumulates a PEL nothing drains: every worker needs every
    message, so nobody acks on behalf of the others. co-core states the rule;
    this makes OWNED_GROUPS unable to express a violation of it.

    Stronger than the guard it replaces. ``StreamCheck.pending_group`` was
    optional, so the check had to be skipped for every groupless row; every
    ``OwnedGroup`` names a group by construction, so the guard always runs.
    """
    with pytest.raises(ValueError, match="config_state"):
        OwnedGroup(INFO_REGISTRY, "archiver.registry")


def test_owned_group_allows_a_fact_stream() -> None:
    """The guard must not overreach: fact streams are exactly where groups live.

    The group name is deliberately *not* a conventional one. The guard keys on
    the topic's kind and must have no opinion about the group's spelling -
    asserting with ``archiver.revisions`` would leave both behaviours
    consistent with a pass.
    """
    assert OwnedGroup(CONTENT_REVISIONS, "not-a-convention").group == "not-a-convention"


def test_owned_group_allows_a_command_stream() -> None:
    """``command`` is the third kind, and it takes exactly one group."""
    assert OwnedGroup(CONTENT_REPLICATE, "also-not-a-convention").group == "also-not-a-convention"


def test_owned_group_tolerates_a_topic_outside_the_taxonomy() -> None:
    """``stream_kind`` signals "not canonical" by raising ``ValueError``, and
    co-core publishes no public set of canonical topics to test membership
    against, so the guard has to run through the exception - which makes it
    fail *open*. A synthetic name must therefore be accepted rather than
    rejected, and ``test_every_owned_topic_is_classifiable`` is the tripwire
    for the case where that open failure starts covering a real stream."""
    assert OwnedGroup("not.a.real.stream", "some.group").group == "some.group"


@pytest.mark.parametrize("topic", [g.topic for g in OWNED_GROUPS])
def test_every_owned_topic_is_classifiable(topic: str) -> None:
    """``OwnedGroup``'s guard fails *open* on a ``ValueError`` from
    ``stream_kind``. That swallow is unavoidable, so its safety rests on
    ``ValueError`` meaning "not canonical" and nothing else. If a future
    co-core stopped classifying a topic archiver consumes, the guard would
    quietly stop guarding it and no other test would notice. This is the
    tripwire.

    The kinds come from ``get_args(StreamKind)`` rather than a copied tuple, so
    co-core legitimately adding a fourth kind does not fail this test for the
    wrong reason.
    """
    assert stream_kind(topic) in get_args(StreamKind)
