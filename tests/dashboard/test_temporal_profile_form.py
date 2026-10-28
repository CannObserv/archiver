"""The dashboard's temporal-profile row: form parsing and the readout (archiver#365). Pure."""

from datetime import UTC, date, datetime

import pytest

from src.core.models.temporal_profile import TemporalProfile
from src.dashboard.temporal_profile_form import fields_from_form, profile_view


def _form(**kw) -> dict:
    return {
        "profile_type": "event",
        "reference_date": "2026-11-15",
        "date_range_start": "",
        "date_range_end": "",
        "rules": "30:6h, 7:1h",
        "post_action": "deactivate",
        "is_active": "on",
    } | kw


def test_an_event_form_becomes_the_service_fields():
    fields, problems = fields_from_form(_form())

    assert problems == []
    assert fields == {
        "profile_type": "event",
        "reference_date": date(2026, 11, 15),
        "date_range_start": None,
        "date_range_end": None,
        "rules": [{"days_before": 30, "interval": "6h"}, {"days_before": 7, "interval": "1h"}],
        "post_action": "deactivate",
        "is_active": True,
    }


def test_a_seasonal_rule_is_a_bare_interval_and_the_other_dates_are_dropped():
    """The form posts every date input; only the type's own reach the service."""
    fields, problems = fields_from_form(
        _form(
            profile_type="seasonal",
            date_range_start="2026-12-01",
            date_range_end="2027-01-15",
            rules=" 2h ",
        )
    )

    assert problems == []
    assert fields["reference_date"] is None
    assert (fields["date_range_start"], fields["date_range_end"]) == (
        date(2026, 12, 1),
        date(2027, 1, 15),
    )
    assert fields["rules"] == [{"interval": "2h"}]


def test_an_unchecked_box_is_inactive_and_blank_rules_are_none():
    fields, problems = fields_from_form(_form(rules="", is_active=None))

    assert problems == []
    assert fields["rules"] == []
    assert fields["is_active"] is False


@pytest.mark.parametrize(
    ("form", "fragment"),
    [
        (_form(reference_date="15/11/2026"), "reference_date"),
        (_form(rules="30-6h"), "30-6h"),
        (_form(rules="thirty:6h"), "thirty:6h"),
        (
            _form(profile_type="seasonal", date_range_start="2026-12-01", date_range_end="x"),
            "date_range_end",
        ),
    ],
)
def test_unparseable_input_is_a_problem_naming_it(form, fragment):
    _fields, problems = fields_from_form(form)

    assert any(fragment in p for p in problems)


def test_the_view_summarises_an_event_and_prefills_the_form():
    profile = TemporalProfile(
        profile_type="event",
        reference_date=date(2026, 11, 15),
        rules=[{"days_before": 30, "interval": "6h"}, {"days_before": 7, "interval": "1h"}],
        post_action="deactivate",
        resolved_interval="6h",
        evaluated_on=date(2026, 10, 28),
    )

    view = profile_view(profile)

    assert (
        view["summary"]
        == "Event on 2026-11-15: 30 days out Every 6 hours, 7 days out Hourly; then deactivate"
    )
    assert view["status"] == "Now Every 6 hours (evaluated 2026-10-28)"
    assert view["rules_text"] == "30:6h, 7:1h"
    assert view["form"]["reference_date"] == "2026-11-15"


def test_the_view_says_when_a_profile_is_silent_off_or_fired():
    profile = TemporalProfile(
        profile_type="seasonal",
        date_range_start=date(2026, 12, 1),
        date_range_end=date(2027, 1, 15),
        rules=[{"interval": "2h"}],
        post_action="reduce_frequency",
        resolved_interval=None,
        evaluated_on=date(2027, 1, 16),
        fired_at=datetime(2027, 1, 16, 0, 5, tzinfo=UTC),
    )

    view = profile_view(profile)

    assert view["summary"] == "Seasonal 2026-12-01 to 2027-01-15: ~2 hr; then reduce frequency"
    assert view["status"] == "Not setting the cadence (evaluated 2027-01-16); fired 2027-01-16"
    assert view["rules_text"] == "2h"

    profile.is_active = False
    assert profile_view(profile)["status"].startswith("Off")


def test_no_profile_has_no_view():
    assert profile_view(None) is None
