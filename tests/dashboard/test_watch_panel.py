"""Tests for the local watch-panel context (archiver#151).

Pure-function coverage of the panel's four states, the health rule, next-due
derivation, cadence drift, the pending-toggle hint, and the generation drift
detector — no DB, no SDK.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from src.dashboard.watch_panel import (
    build_watch_context,
    format_interval,
    parse_interval_seconds,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def make_item(**overrides):
    defaults = dict(
        watch_spec={"schema_version": 1, "interval": "1d"},
        watch_active=None,
        watcher_item_id="wi-1",
        announcement_generation=3,
        announced_at=NOW - timedelta(minutes=5),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_status(**overrides):
    defaults = dict(
        applied_generation=3,
        applied_active=True,
        applied_interval=None,
        last_attempt_at=NOW - timedelta(hours=2),
        last_observed_at=NOW - timedelta(hours=2),
        health="ok",
        occurred_at=NOW - timedelta(minutes=1),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestIntervals:
    def test_parse_valid(self):
        assert parse_interval_seconds("30s") == 30
        assert parse_interval_seconds("5m") == 300
        assert parse_interval_seconds("6h") == 21600
        assert parse_interval_seconds("7d") == 604800

    def test_parse_invalid(self):
        assert parse_interval_seconds(None) is None
        assert parse_interval_seconds("") is None
        assert parse_interval_seconds("1w") is None
        assert parse_interval_seconds("daily") is None

    def test_format_friendly_and_generic(self):
        assert format_interval("1h") == "Hourly"
        assert format_interval("6h") == "Every 6 hours"
        assert format_interval("1d") == "Daily"
        assert format_interval("7d") == "Weekly"
        assert format_interval("3h") == "~3 hr"
        assert format_interval("2d") == "~2 days"
        assert format_interval("1d ") == "Daily"  # whitespace tolerated
        assert format_interval("bogus") == ""
        assert format_interval(None) == ""

    def test_format_generic_covers_every_unit(self):
        """`_UNIT_LABELS` carries s/m/h/d; the minute and second arms had no
        test after the SDK-era cadence tests were retired."""
        assert format_interval("30s") == "~30 sec"
        assert format_interval("15m") == "~15 min"
        assert format_interval("1d") == "Daily"


class TestStates:
    def test_not_watching_when_never_provisioned(self):
        ctx = build_watch_context(
            item=make_item(watcher_item_id=None),
            status=None,
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["state"] == "not_watching"

    def test_no_status_is_the_fourth_state(self):
        """Provisioned but Watcher has never reported: not paused, not healthy."""
        ctx = build_watch_context(item=make_item(), status=None, last_changed_at=None, now=NOW)
        assert ctx["state"] == "no_status"
        assert ctx["health_ok"] is False
        assert ctx["applied_active"] is None

    def test_no_status_still_shows_announced_cadence_and_last_changed(self):
        ctx = build_watch_context(
            item=make_item(),
            status=None,
            last_changed_at=NOW - timedelta(days=2),
            now=NOW,
        )
        assert ctx["cadence"] == "Daily"
        assert ctx["last_changed_ago"] == "2 days ago"

    def test_watching_with_status_row(self):
        ctx = build_watch_context(
            item=make_item(), status=make_status(), last_changed_at=None, now=NOW
        )
        assert ctx["state"] == "watching"
        assert ctx["health_ok"] is True
        assert ctx["last_attempt_ago"] == "2 hr ago"


class TestHealthRule:
    def test_only_ok_is_healthy(self):
        for value in ("error", "degraded", "some-future-token"):
            ctx = build_watch_context(
                item=make_item(),
                status=make_status(health=value),
                last_changed_at=None,
                now=NOW,
            )
            assert ctx["health_ok"] is False, value
            assert ctx["health"] == value  # renders verbatim

    def test_paused_is_a_state_not_absence(self):
        ctx = build_watch_context(
            item=make_item(),
            status=make_status(applied_active=False),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["state"] == "watching"
        assert ctx["applied_active"] is False


class TestNextDue:
    def test_derives_from_attempt_plus_announced_interval(self):
        # last attempt 2h ago, daily cadence → due in 22h
        ctx = build_watch_context(
            item=make_item(), status=make_status(), last_changed_at=None, now=NOW
        )
        assert ctx["next_due"] == "in 22h"
        assert ctx["overdue"] is False

    def test_applied_interval_wins_over_announced(self):
        """Deriving from the announcement alone reports a schedule Watcher is
        not running (epic open hole #2)."""
        ctx = build_watch_context(
            item=make_item(),
            status=make_status(applied_interval="1h"),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["next_due"] == "overdue by 1h"
        assert ctx["overdue"] is True
        assert ctx["cadence_drift"] is True
        assert ctx["applied_cadence"] == "Hourly"

    def test_no_interval_no_next_due(self):
        ctx = build_watch_context(
            item=make_item(watch_spec={"schema_version": 1}),
            status=make_status(),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["next_due"] is None

    def test_no_attempt_no_next_due(self):
        ctx = build_watch_context(
            item=make_item(),
            status=make_status(last_attempt_at=None),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["next_due"] is None


class TestPendingToggle:
    def test_desired_pause_not_yet_applied(self):
        ctx = build_watch_context(
            item=make_item(watch_active=False),
            status=make_status(applied_active=True),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["pending_toggle"] == "pause"

    def test_no_hint_when_aligned_or_no_opinion(self):
        aligned = build_watch_context(
            item=make_item(watch_active=True),
            status=make_status(applied_active=True),
            last_changed_at=None,
            now=NOW,
        )
        assert aligned["pending_toggle"] is None
        no_opinion = build_watch_context(
            item=make_item(watch_active=None),
            status=make_status(applied_active=False),
            last_changed_at=None,
            now=NOW,
        )
        assert no_opinion["pending_toggle"] is None


class TestDrift:
    def test_in_sync(self):
        ctx = build_watch_context(
            item=make_item(announcement_generation=7),
            status=make_status(applied_generation=7),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["drift"] == {
            "announced": 7,
            "applied": 7,
            "in_drift": False,
            "ahead": False,
            "alert": False,
            "age": None,
        }

    def test_drift_below_threshold_is_not_an_alert(self):
        ctx = build_watch_context(
            item=make_item(announcement_generation=9, announced_at=NOW - timedelta(minutes=5)),
            status=make_status(applied_generation=7),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["drift"]["in_drift"] is True
        assert ctx["drift"]["alert"] is False
        assert ctx["drift"]["age"] == "5m"

    def test_drift_past_threshold_alerts(self):
        ctx = build_watch_context(
            item=make_item(announcement_generation=9, announced_at=NOW - timedelta(minutes=40)),
            status=make_status(applied_generation=7),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["drift"]["alert"] is True
        assert ctx["drift"]["age"] == "40m"

    def test_never_announced_has_no_drift_line(self):
        ctx = build_watch_context(
            item=make_item(announcement_generation=0, announced_at=None),
            status=make_status(applied_generation=0),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["drift"] is None

    def test_drift_without_announced_at_has_no_age_and_no_alert(self):
        """Pre-#151 rows never stamped announced_at; drift still shows, unaged."""
        ctx = build_watch_context(
            item=make_item(announcement_generation=9, announced_at=None),
            status=make_status(applied_generation=7),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["drift"]["in_drift"] is True
        assert ctx["drift"]["age"] is None
        assert ctx["drift"]["alert"] is False


class TestClearedLinkPrecedence:
    def test_cleared_link_falls_back_to_not_watching_despite_stale_row(self):
        """A WatchedItem deleted in Watcher clears `watcher_item_id` on the next
        action. If a stale cache row still rendered `watching`, the panel would
        offer no "Begin Watching" affordance and the operator could not
        re-provision — a dead end on a live recovery path.
        """
        ctx = build_watch_context(
            item=make_item(watcher_item_id=None),
            status=make_status(),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["state"] == "not_watching"

    def test_stale_row_never_reported_as_health_of_a_relinked_item(self):
        """The same guard stops an old WatchedItem's health leaking onto an item
        that has since been re-provisioned under a new id."""
        ctx = build_watch_context(
            item=make_item(watcher_item_id=None),
            status=make_status(health="error", applied_active=False),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["health"] is None
        assert ctx["applied_active"] is None


class TestDriftAhead:
    def test_applied_ahead_of_announced_is_not_in_sync(self):
        """A restored-from-backup registry can sit *behind* the consumer.
        Rendering that as ✓ fails in the silent direction."""
        ctx = build_watch_context(
            item=make_item(announcement_generation=5),
            status=make_status(applied_generation=7),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["drift"]["ahead"] is True
        assert ctx["drift"]["in_drift"] is False
        assert ctx["drift"]["alert"] is False

    def test_in_sync_is_not_flagged_ahead(self):
        ctx = build_watch_context(
            item=make_item(announcement_generation=7),
            status=make_status(applied_generation=7),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["drift"]["ahead"] is False
        assert ctx["drift"]["in_drift"] is False


class TestPathologicalInterval:
    """A reported interval the arithmetic cannot hold must degrade, not raise.

    `applied_interval` is an unconstrained `str` from a service we do not
    control, and the column is TEXT since CR round 1, so nothing upstream caps
    it. `timedelta` overflows well before Python's int does — and the value is
    already persisted by the time the panel reads it, so an unguarded raise
    breaks the page on every subsequent load, not just once.
    """

    def test_absurd_interval_yields_no_next_due_instead_of_raising(self):
        ctx = build_watch_context(
            item=make_item(),
            status=make_status(applied_interval="99999999999d"),
            last_changed_at=None,
            now=NOW,
        )
        assert ctx["next_due"] is None
        assert ctx["overdue"] is False
        assert ctx["state"] == "watching"

    def test_absurd_interval_still_renders_verbatim(self):
        """Out of range for scheduling is not the same as untrue — the operator
        should still see what Watcher reported."""
        ctx = build_watch_context(
            item=make_item(),
            status=make_status(applied_interval="99999999999d"),
            last_changed_at=None,
            now=NOW,
        )
        assert "99999999999" in ctx["applied_cadence"]

    def test_parse_rejects_out_of_range_but_accepts_long_sane_ones(self):
        assert parse_interval_seconds("99999999999d") is None
        assert parse_interval_seconds("365d") == 365 * 86400
