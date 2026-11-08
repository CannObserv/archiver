"""The check-now block's context (archiver#370): a ``CheckState`` made renderable.

Pure: the route reads the item's latest ``watch_check_commands`` row and its
``watch_status`` row, ``src.core.services.watch_check.check_state`` places them
on the ladder, and this turns the result into what ``_watch_check.html`` shows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TypedDict

from src.core.services.watch_check import CheckState
from src.dashboard.watch_panel import format_age

#: How often the block re-reads itself while its command is pending.
POLL_SECONDS = 5

#: The stream a dead-lettered command lands on - Watcher's, probed by broker.
DLQ = "info.watch-check.dlq"


class CheckView(TypedDict):
    kind: str
    open: bool
    requested_ago: str | None
    completed_ago: str | None
    reason: str | None
    health: str | None
    health_ok: bool
    health_reason: str | None
    health_status_code: int | None
    timeout_minutes: int
    dlq: str


def check_view(state: CheckState | None, *, now: datetime, timeout: timedelta) -> CheckView | None:
    """``None`` for an item never checked; else the block's fields for ``state``."""
    if state is None:
        return None
    return CheckView(
        kind=state.kind,
        open=state.open,
        requested_ago=format_age(state.requested_at, now=now),
        completed_ago=format_age(state.completed_at, now=now),
        reason=state.reason,
        health=state.health,
        health_ok=state.health_ok,
        health_reason=state.health_reason,
        health_status_code=state.health_status_code,
        timeout_minutes=max(1, int(timeout.total_seconds() // 60)),
        dlq=DLQ,
    )
