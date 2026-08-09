"""Loop pacing shared by the outbox publisher and the bus consumer.

Both run the same shape: a background asyncio loop against a broker that can be
down, where a failing iteration must back off rather than spin, and a sustained
outage must not flood journald. The numbers below encode incident history
(archiver#107 dead-lettering, archiver#128's shared-broker OOM), which is exactly
why they are shared rather than copied — a copy stops tracking the original
silently, and this repo has already paid for that lesson once with the co-core
mirror (CR round 1, finding 5).
"""

from __future__ import annotations

# Escalating backoff for a whole-iteration failure (broker unreachable, DB down).
ERROR_BACKOFF_BASE_SECONDS = 1.0
ERROR_BACKOFF_MAX_SECONDS = 30.0
# Cap the exponent so ``base * 2**shift`` cannot overflow before the max applies.
ERROR_BACKOFF_MAX_SHIFT = 5
# Log the first failure, then every Nth, so a sustained outage cannot flood the
# journal at one line per iteration.
ERROR_LOG_EVERY = 15


def error_backoff_seconds(
    consecutive_failures: int, base: float = ERROR_BACKOFF_BASE_SECONDS
) -> float:
    """Exponential backoff (``base * 2**(n-1)``) capped at ``ERROR_BACKOFF_MAX_SECONDS``.

    ``consecutive_failures <= 1`` yields ``base``; the exponent is clamped so the
    intermediate never overflows before the cap is applied.
    """
    if consecutive_failures <= 1:
        return min(base, ERROR_BACKOFF_MAX_SECONDS)
    shift = min(consecutive_failures - 1, ERROR_BACKOFF_MAX_SHIFT)
    return min(base * (2**shift), ERROR_BACKOFF_MAX_SECONDS)
