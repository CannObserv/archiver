"""WatchSpec validator wrapper tests."""

from src.core.watch_spec_schema.validator import DEFAULT_WATCH_SPEC, validate_watch_spec


def test_validate_watch_spec_ok_without_interval():
    """interval is optional — absence means 'consumer applies its default'."""
    ok, errs = validate_watch_spec({"schema_version": 1, "active": True})
    assert ok is True
    assert errs == []


def test_validate_watch_spec_ok_with_interval():
    ok, errs = validate_watch_spec({"schema_version": 1, "active": True, "interval": "1d"})
    assert ok is True
    assert errs == []


def test_validate_watch_spec_accepts_intervals_outside_the_dashboard_options():
    """The schema validates the grammar Watcher parses, not the four UI options.

    A live per-domain default_schedule_config can hold any s/m/h/d interval, and
    the one-time import must not reject one.
    """
    for interval in ("30m", "12h", "90s", "14d"):
        ok, errs = validate_watch_spec({"schema_version": 1, "active": True, "interval": interval})
        assert ok is True, (interval, errs)


def test_validate_watch_spec_rejects_unparseable_interval():
    for interval in ("daily", "1w", "1", "d1", "", "1 d"):
        ok, _ = validate_watch_spec({"schema_version": 1, "active": True, "interval": interval})
        assert ok is False, interval


def test_validate_watch_spec_rejects_null_interval():
    """Absence is the one representation of 'consumer default'; null is not a second."""
    ok, _ = validate_watch_spec({"schema_version": 1, "active": True, "interval": None})
    assert ok is False


def test_validate_watch_spec_requires_active():
    ok, errs = validate_watch_spec({"schema_version": 1, "interval": "1d"})
    assert ok is False
    assert any("active" in e["message"] for e in errs)


def test_validate_watch_spec_requires_schema_version():
    ok, _ = validate_watch_spec({"active": True})
    assert ok is False


def test_validate_watch_spec_rejects_wrong_schema_version():
    ok, _ = validate_watch_spec({"schema_version": 2, "active": True})
    assert ok is False


def test_validate_watch_spec_rejects_non_boolean_active():
    ok, _ = validate_watch_spec({"schema_version": 1, "active": "true"})
    assert ok is False


def test_validate_watch_spec_rejects_extra_property():
    ok, _ = validate_watch_spec(
        {"schema_version": 1, "active": True, "jitter": "10m"},
    )
    assert ok is False


def test_validate_watch_spec_returns_structured_errors():
    ok, errs = validate_watch_spec({"schema_version": 1, "active": True, "interval": "daily"})
    assert ok is False
    assert len(errs) >= 1
    assert all("path" in e and "message" in e for e in errs)
    assert any(e["path"] == "/interval" for e in errs)


def test_default_watch_spec_is_valid_and_carries_no_interval():
    """The migration's server default must not fabricate a cadence."""
    ok, errs = validate_watch_spec(DEFAULT_WATCH_SPEC)
    assert ok is True, errs
    assert "interval" not in DEFAULT_WATCH_SPEC
    assert DEFAULT_WATCH_SPEC["active"] is True
