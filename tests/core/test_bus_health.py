"""Tests for the broker-side bus-health probes (archiver#130).

The pure ``evaluate_*`` functions carry the thresholds; the ``collect_*``
functions are exercised against fakeredis so the Redis command surface
(XLEN / XINFO STREAM / XPENDING / SCAN) is real, not mocked. The two-tick
pending rule and the state file that carries it between oneshot runs get
their own coverage because the timer is stateless without them.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from co_core.pure.adapters.bus.streams import (
    CONTENT_FETCH_POLICY,
    CONTENT_REVISIONS,
    INFO_REGISTRY,
)
from fakeredis import aioredis as fakeredis_aio

from src.core import bus_health
from src.core.bus_health import (
    DISK_WARN_MIN_FREE_BYTES,
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
)
from src.core.changes.outbox_stats import OutboxStats


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


async def test_run_once_persists_state(fake_redis, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    await bus_health.run_once(
        fake_redis,
        session_factory=None,
        state_path=state_path,
        disk_usage=_healthy_disk,
    )
    assert json.loads(state_path.read_text()) == {}
