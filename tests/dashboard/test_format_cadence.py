"""Unit tests for _format_cadence.

Watcher stores cadence as {"interval": "<N><unit>"} (unit s/m/h/d), not
{"interval_seconds": int}. See watcher/src/core/scheduler.py parse_interval.
"""

from __future__ import annotations

from src.dashboard.routes.info_items import _format_cadence


class _Cfg:
    """Minimal stand-in for WatchedItemResponseDefaultScheduleConfigType0."""

    def __init__(self, **props):
        self.additional_properties = dict(props)


def test_none_config_returns_empty():
    assert _format_cadence(None) == ""


def test_missing_interval_returns_empty():
    assert _format_cadence(_Cfg()) == ""


def test_object_without_additional_properties_returns_empty():
    assert _format_cadence(object()) == ""


# Recognised registration cadences render with their friendly label.


def test_hours_interval_friendly_label():
    assert _format_cadence(_Cfg(interval="6h")) == "Every 6 hours"


def test_one_hour_friendly_label():
    assert _format_cadence(_Cfg(interval="1h")) == "Hourly"


def test_daily_interval_friendly_label():
    assert _format_cadence(_Cfg(interval="1d")) == "Daily"


def test_weekly_interval_friendly_label():
    assert _format_cadence(_Cfg(interval="7d")) == "Weekly"


# Arbitrary (non-registration) Watcher intervals fall back to the generic form.


def test_minutes_interval_generic_fallback():
    assert _format_cadence(_Cfg(interval="15m")) == "~15 min"


def test_seconds_interval_generic_fallback():
    assert _format_cadence(_Cfg(interval="30s")) == "~30 sec"


def test_unknown_days_generic_fallback_pluralizes():
    assert _format_cadence(_Cfg(interval="3d")) == "~3 days"


def test_unparseable_interval_returns_empty():
    assert _format_cadence(_Cfg(interval="banana")) == ""


def test_legacy_interval_seconds_key_ignored():
    # The old (wrong) key must no longer be honored.
    assert _format_cadence(_Cfg(interval_seconds=3600)) == ""
