"""Periodic sweep for replication commands that produced no fact (archiver#170).

MUST-6's obligation, and the reason it is a *timer* rather than something the
``content.artifacts`` consumer does on the side: the condition it detects is the
**absence** of a message. A sweep driven by arrivals would never fire in exactly
the case it exists for — Replicator retrying a provider 5xx unboundedly, silently,
publishing nothing at all while it does.

Shaped after ``registry_snapshot``: its own task, sharing the publisher's stop
event, failing without touching anything else. It publishes nothing and re-issues
nothing — see ``reap_open_commands`` for why an automatic retry into a permanent
store is the wrong default.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes.backoff import ERROR_BACKOFF_BASE_SECONDS, error_backoff_seconds
from src.core.logging import get_logger
from src.core.services.replication_writeback import DEFAULT_REAP_HORIZON, reap_open_commands

logger = get_logger(__name__)

# How often to sweep. Well under the horizon so a command crosses it in one
# period rather than one-and-a-bit, and far too rare to matter as load.
DEFAULT_INTERVAL_SECONDS = 900.0

_MIN_INTERVAL_SECONDS = 60.0
_MIN_HORIZON_SECONDS = 300.0


def resolve_interval(raw: str | None, default: float = DEFAULT_INTERVAL_SECONDS) -> float:
    """Parse ``ARCHIVER_REPLICATION_REAP_INTERVAL`` defensively.

    A malformed knob degrades to the default rather than killing the task — the
    ``resolve_stream_maxlen`` precedent: an operator typo must not silently
    disable a safety net.
    """
    return _positive_float(raw, default, _MIN_INTERVAL_SECONDS, "reap interval")


def resolve_horizon(raw: str | None, default: timedelta = DEFAULT_REAP_HORIZON) -> timedelta:
    """Parse ``ARCHIVER_REPLICATION_REAP_HORIZON`` (seconds) defensively.

    Floored well above a plausible provider retry burst: abandoning a command
    Replicator is still working on turns a slow success into a permanent-looking
    failure in the dashboard.
    """
    seconds = _positive_float(raw, default.total_seconds(), _MIN_HORIZON_SECONDS, "reap horizon")
    return timedelta(seconds=seconds)


def _positive_float(raw: str | None, default: float, minimum: float, label: str) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring malformed %s; using default", label, extra={"value": raw})
        return default
    if value < minimum:
        logger.warning(
            "Clamping %s to its floor",
            label,
            extra={"value": value, "minimum": minimum},
        )
        return minimum
    return value


async def sweep_once(
    session_factory: async_sessionmaker[AsyncSession], *, horizon: timedelta
) -> int:
    """One pass. Returns how many commands were abandoned."""
    async with session_factory() as session:
        reaped = await reap_open_commands(session, horizon=horizon)
        if reaped:
            await session.commit()
    return reaped


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    horizon: timedelta = DEFAULT_REAP_HORIZON,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
) -> None:
    """Sweep every ``interval`` seconds until ``stop_event`` is set.

    Sweeps once at startup: a process that crashed mid-outage comes back to a
    backlog of commands already past the horizon, and waiting a full period to
    notice serves nobody.
    """
    logger.info(
        "Replication reaper starting",
        extra={"interval_seconds": interval, "horizon_hours": horizon.total_seconds() / 3600},
    )
    consecutive_failures = 0
    while not stop_event.is_set():
        try:
            reaped = await sweep_once(session_factory, horizon=horizon)
            if reaped:
                logger.warning(
                    "Abandoned replication commands past the horizon",
                    extra={"reaped": reaped, "horizon_hours": horizon.total_seconds() / 3600},
                )
            consecutive_failures = 0
            delay = interval
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            logger.exception(
                "Replication reaper sweep failed; backing off",
                extra={"consecutive_failures": consecutive_failures},
            )
            delay = error_backoff_seconds(consecutive_failures, error_backoff_base)

        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=delay,
            return_when=asyncio.FIRST_COMPLETED,
        )
