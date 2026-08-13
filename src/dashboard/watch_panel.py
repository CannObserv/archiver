"""Watched-item panel context, computed from local state (archiver#151).

Pure functions: the routes load ``InfoItem`` + ``WatchStatus`` + the latest
revision timestamp and everything here is arithmetic on them — no SDK, no I/O.
The panel renders with zero Watcher calls; the SDK survives only behind the
action buttons until the control-plane cutover (archiver#158) and teardown
(archiver#142).

**The four states.** ``not_watching`` (never provisioned), ``no_status``
(provisioned but Watcher has never reported — a booting consumer with an empty
replay and a genuinely silent Watcher land here, *distinct* from paused and
from healthy), ``watching`` (a status row exists; paused is a badge within
it), and ``degraded`` (an *action* against Watcher failed; the local render
path itself cannot degrade).

**Health.** Open vocabulary: ``"ok"`` is the only value that means healthy.
Every other value — ``"error"``, a future ``"degraded"``, one never seen —
is non-healthy and renders verbatim. Never test ``health != "error"``.

**Next due** derives from ``last_attempt_at`` (a failing item attempts on
schedule while ``last_observed_at`` stands still) plus ``applied_interval``
where present — the cadence Watcher is actually running — falling back to the
announced ``watch_spec`` interval. ``next_due_at`` is deliberately not on the
wire: it moves every cycle and would have made the stream activity-rate-scaled.

**Drift.** ``info_items.announcement_generation`` against
``applied_generation``, aged from ``info_items.announced_at``; past
``DRIFT_ALERT_THRESHOLD`` it is an alert, not a curiosity.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, TypedDict

from src.dashboard.cadence import CADENCE_LABELS

if TYPE_CHECKING:
    from src.core.models import InfoItem, WatchStatus

# How long applied may lag announced before the panel escalates the drift line
# to an alert. Delta propagation is seconds and the snapshot repair is hourly,
# so 15 minutes of lag means the announcement path is genuinely stuck, not slow.
DRIFT_ALERT_THRESHOLD = timedelta(minutes=15)

_INTERVAL_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_UNIT_LABELS = {"s": "sec", "m": "min", "h": "hr", "d": "day"}


def parse_interval_seconds(interval: str | None) -> int | None:
    """Seconds for a Watcher interval string (``^[0-9]+[smhd]$``), else None."""
    if not interval:
        return None
    match = _INTERVAL_RE.fullmatch(str(interval).strip())
    if match is None:
        return None
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def format_interval(interval: str | None) -> str:
    """Human label for an interval string: friendly where offered, ``~N unit``
    otherwise, ``""`` for absent/unparseable — same contract the SDK-era
    ``_format_cadence`` had."""
    if not interval:
        return ""
    interval = str(interval).strip()
    if interval in CADENCE_LABELS:
        return CADENCE_LABELS[interval]
    match = _INTERVAL_RE.fullmatch(interval)
    if match is None:
        return ""
    amount = int(match.group(1))
    unit = match.group(2)
    plural = "s" if (unit == "d" and amount != 1) else ""
    return f"~{amount} {_UNIT_LABELS[unit]}{plural}"


def format_age(dt: datetime | None, *, now: datetime) -> str | None:
    """Short relative age ("just now" / "5 min ago" / "2 days ago")."""
    if dt is None:
        return None
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    seconds = max(0, int((now - aware).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} hr ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def _format_span(seconds: int) -> str:
    """Compact duration for drift ages and due offsets ("40m", "3h", "2d")."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


class DriftContext(TypedDict):
    announced: int
    applied: int
    in_drift: bool
    alert: bool
    age: str | None


class WatchPanelContext(TypedDict):
    state: str
    health: str | None
    health_ok: bool
    applied_active: bool | None
    desired_active: bool | None
    pending_toggle: str | None
    cadence: str
    applied_cadence: str
    cadence_drift: bool
    last_attempt_ago: str | None
    last_observed_ago: str | None
    last_changed_ago: str | None
    next_due: str | None
    overdue: bool
    drift: DriftContext | None


def _drift(item: InfoItem, status: WatchStatus, *, now: datetime) -> DriftContext | None:
    announced = item.announcement_generation
    if announced <= 0:
        return None  # never announced — there is nothing to lag behind
    applied = status.applied_generation
    in_drift = applied < announced
    age_seconds: int | None = None
    if in_drift and item.announced_at is not None:
        age_seconds = max(0, int((now - item.announced_at).total_seconds()))
    return DriftContext(
        announced=announced,
        applied=applied,
        in_drift=in_drift,
        alert=in_drift
        and age_seconds is not None
        and age_seconds > DRIFT_ALERT_THRESHOLD.total_seconds(),
        age=_format_span(age_seconds) if age_seconds is not None else None,
    )


def build_watch_context(
    *,
    item: InfoItem,
    status: WatchStatus | None,
    last_changed_at: datetime | None,
    now: datetime,
) -> WatchPanelContext:
    """The whole panel, from three local facts."""
    announced_interval = (item.watch_spec or {}).get("interval")

    if status is None:
        # Provisioned-but-silent is the fourth state; never-provisioned is the
        # first. The split key is watcher_item_id until #142 removes it, after
        # which an active binding takes over the role.
        state = "no_status" if item.watcher_item_id else "not_watching"
        return WatchPanelContext(
            state=state,
            health=None,
            health_ok=False,
            applied_active=None,
            desired_active=item.watch_active,
            pending_toggle=None,
            cadence=format_interval(announced_interval),
            applied_cadence="",
            cadence_drift=False,
            last_attempt_ago=None,
            last_observed_ago=None,
            last_changed_ago=format_age(last_changed_at, now=now),
            next_due=None,
            overdue=False,
            drift=None,
        )

    effective_interval = status.applied_interval or announced_interval
    next_due: str | None = None
    overdue = False
    interval_seconds = parse_interval_seconds(effective_interval)
    if interval_seconds is not None and status.last_attempt_at is not None:
        due_at = status.last_attempt_at + timedelta(seconds=interval_seconds)
        delta = int((due_at - now).total_seconds())
        if delta >= 0:
            next_due = f"in {_format_span(delta)}"
        else:
            next_due = f"overdue by {_format_span(-delta)}"
            overdue = True

    # A cadence-only divergence is invisible in the generations: applied_active
    # holds, applied_generation catches up, and the panel would read clean while
    # the announced policy is ignored — applied_interval exists for exactly this.
    cadence_drift = (
        status.applied_interval is not None
        and announced_interval is not None
        and status.applied_interval != announced_interval
    )

    pending_toggle: str | None = None
    if item.watch_active is not None and status.applied_active is not None:
        if item.watch_active != status.applied_active:
            pending_toggle = "resume" if item.watch_active else "pause"

    return WatchPanelContext(
        state="watching",
        health=status.health,
        health_ok=status.health == "ok",
        applied_active=status.applied_active,
        desired_active=item.watch_active,
        pending_toggle=pending_toggle,
        cadence=format_interval(announced_interval),
        applied_cadence=format_interval(status.applied_interval),
        cadence_drift=cadence_drift,
        last_attempt_ago=format_age(status.last_attempt_at, now=now),
        last_observed_ago=format_age(status.last_observed_at, now=now),
        last_changed_ago=format_age(last_changed_at, now=now),
        next_due=next_due,
        overdue=overdue,
        drift=_drift(item, status, now=now),
    )
