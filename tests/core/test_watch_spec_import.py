"""Pure mapping from Watcher's fields onto the registry's two policy columns."""

from src.core.watch_spec_import import plan_item_import, watch_spec_from_schedule_config


def _plan(**overrides):
    kwargs = dict(
        watcher_item_id=None,
        watch_spec={"schema_version": 1},
        watch_active=None,
        wi_id="01HZZWATCHER00000000000001",
        wi_is_active=True,
        wi_schedule_config=None,
    )
    kwargs.update(overrides)
    return plan_item_import(**kwargs)


def test_absent_schedule_config_produces_no_interval():
    """Watcher holding no per-item cadence is a real state, not a missing value."""
    assert watch_spec_from_schedule_config(None) == {"schema_version": 1}


def test_schedule_config_interval_is_carried_through():
    assert watch_spec_from_schedule_config({"interval": "6h"}) == {
        "schema_version": 1,
        "interval": "6h",
    }


def test_the_document_never_carries_active():
    """Pause state is a sibling column; a nested key would validate silently on the wire."""
    assert "active" not in watch_spec_from_schedule_config({"interval": "1d"})


def test_plan_reports_a_change_when_only_the_active_flag_differs():
    """watch_active NULL → False is an import, even with the cadence unchanged."""
    plan = _plan(wi_is_active=False)
    assert plan.changed is True
    assert plan.watch_active is False


def test_plan_reports_no_change_when_both_columns_already_match():
    plan = _plan(
        watch_spec={"schema_version": 1, "interval": "1d"},
        watch_active=True,
        wi_schedule_config={"interval": "1d"},
    )
    assert plan.changed is False


def test_unparseable_interval_is_an_error_and_the_plan_does_not_apply():
    plan = _plan(wi_schedule_config={"interval": "weekly"})
    assert plan.error is not None
    assert "weekly" in plan.error
    assert plan.changed is False


def test_watcher_item_id_mismatch_is_an_anomaly_but_still_applies():
    plan = _plan(
        watcher_item_id="01HZZSTALE0000000000000000", wi_schedule_config={"interval": "1h"}
    )
    assert plan.anomaly is not None
    assert "watcher_item_id" in plan.anomaly
    assert plan.error is None
    assert plan.watch_spec == {"schema_version": 1, "interval": "1h"}
