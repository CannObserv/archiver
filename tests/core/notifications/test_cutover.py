"""The cutover instant T (archiver#369, D3).

One switch: unset is shadow. A row is ``send`` only when T is set and its
instant is at or after T. T without the Notifier gate refuses startup, and so
does a T that isn't an unambiguous UTC instant: a misread T is a double send or
a gap at F3.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from src.core.notifications.cutover import (
    CUTOVER_ENV,
    CutoverRefused,
    announce_cutover,
    mode_for,
    resolve_cutover,
)

T = datetime(2026, 11, 20, 17, 0, tzinfo=UTC)


def test_unset_is_shadow():
    assert resolve_cutover({}, notifier_configured=True) is None
    assert resolve_cutover({}, notifier_configured=False) is None


def test_blank_is_unset():
    assert resolve_cutover({CUTOVER_ENV: "  "}, notifier_configured=False) is None


@pytest.mark.parametrize(
    "raw",
    ["2026-11-20T17:00:00Z", "2026-11-20T17:00:00.000000Z", "2026-11-20T17:00:00+00:00"],
)
def test_an_iso_utc_instant_is_read(raw):
    assert resolve_cutover({CUTOVER_ENV: raw}, notifier_configured=True) == T


@pytest.mark.parametrize(
    "raw",
    [
        "2026-11-20T17:00:00",  # naive: whose clock?
        "2026-11-20T19:00:00+02:00",  # not UTC, as the env reference requires
        "2026-11-20",
        "tomorrow",
        "1763658000",
    ],
)
def test_anything_else_refuses(raw):
    with pytest.raises(CutoverRefused, match=CUTOVER_ENV):
        resolve_cutover({CUTOVER_ENV: raw}, notifier_configured=True)


def test_t_without_the_notifier_gate_refuses():
    """Pending rows nothing could drain: refuse rather than accumulate."""
    with pytest.raises(CutoverRefused, match="Notifier"):
        resolve_cutover({CUTOVER_ENV: "2026-11-20T17:00:00Z"}, notifier_configured=False)


def test_mode_is_shadow_without_t():
    assert mode_for(T + timedelta(days=365), None) == "shadow"


def test_mode_is_send_at_and_after_t():
    assert mode_for(T, T) == "send"
    assert mode_for(T + timedelta(microseconds=1), T) == "send"
    assert mode_for(T - timedelta(microseconds=1), T) == "shadow"


def test_the_journal_says_which(caplog):
    with caplog.at_level(logging.INFO):
        announce_cutover(None)
        announce_cutover(T)
    assert [r.getMessage() for r in caplog.records] == [
        "notify cutover: unset (shadow)",
        "notify cutover: 2026-11-20T17:00:00.000000Z (facts at or after it send)",
    ]
