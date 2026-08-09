"""The retry schedule shared by the outbox publisher and the bus consumer.

Moved out of ``test_publisher.py`` when the schedule itself moved out of
``publisher.py`` (#139 CR round 2, finding 14): both loops now import it, so the
test mirrors the module rather than one of its two callers.
"""

import pytest

from src.core.changes.backoff import (
    ERROR_BACKOFF_BASE_SECONDS,
    ERROR_BACKOFF_MAX_SECONDS,
    ERROR_LOG_EVERY,
    error_backoff_seconds,
)


@pytest.mark.parametrize(
    ("consecutive", "base", "expected"),
    [
        (0, 1.0, 1.0),  # no failures → base
        (1, 1.0, 1.0),  # 1st failure → base
        (2, 1.0, 2.0),  # exponential
        (3, 1.0, 4.0),
        (4, 1.0, 8.0),
        (6, 1.0, min(32.0, ERROR_BACKOFF_MAX_SECONDS)),  # exponent clamped at shift=5
        (100, 1.0, ERROR_BACKOFF_MAX_SECONDS),  # 1.0 * 2**5 = 32 → capped at 30
        (100, 0.25, 8.0),  # 0.25 * 2**5 = 8 → below cap, so NOT capped
    ],
)
def test_error_backoff_seconds(consecutive, base, expected):
    """Consecutive whole-iteration failures back off exponentially, capped (CR #13)."""
    assert error_backoff_seconds(consecutive, base) == expected


def test_base_is_optional():
    """Both loops pass their own knob, but the default is the shared one."""
    assert error_backoff_seconds(1) == ERROR_BACKOFF_BASE_SECONDS


def test_log_throttle_is_a_positive_interval():
    """A zero or negative ERROR_LOG_EVERY would make ``n % EVERY`` raise or log always.

    Both loops spell the throttle as ``failures == 1 or failures % ERROR_LOG_EVERY
    == 0``; the constant is the only thing standing between a sustained outage and
    one journal line per iteration.
    """
    assert ERROR_LOG_EVERY > 1
