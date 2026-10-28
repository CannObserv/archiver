"""Temporal-profile evaluation and validation (archiver#365): Watcher's semantics, ported.

Pure: transient ``TemporalProfile`` objects, no database. The cases Watcher's
own suite pins (``tests/core/scheduling/test_cadence.py`` at ``127eeee``) come
first; the edges it left unpinned follow, table-driven (the coordinator brief's
list).
"""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from src.core.models.temporal_profile import TemporalProfile
from src.core.services.temporal_evaluation import (
    Evaluation,
    evaluate,
    profile_errors,
    utc_today,
    window_end,
)


def _event(ref: date, rules: list[dict], **kw) -> TemporalProfile:
    return TemporalProfile(
        profile_type=kw.pop("profile_type", "event"),
        reference_date=ref,
        rules=rules,
        post_action=kw.pop("post_action", "reduce_frequency"),
        **kw,
    )


def _seasonal(start: date, end: date, interval: str = "1h", **kw) -> TemporalProfile:
    return TemporalProfile(
        profile_type="seasonal",
        date_range_start=start,
        date_range_end=end,
        rules=[{"interval": interval}],
        post_action=kw.pop("post_action", "deactivate"),
        **kw,
    )


REF = date(2026, 4, 15)
RULES_30_7 = [{"days_before": 30, "interval": "6h"}, {"days_before": 7, "interval": "1h"}]


# --- Watcher's own cases -----------------------------------------------------


def test_event_30_days_before_resolves_the_wide_rule():
    assert evaluate(_event(REF, RULES_30_7), date(2026, 3, 21)).interval == "6h"


def test_event_7_days_before_resolves_the_tight_rule():
    assert evaluate(_event(REF, RULES_30_7), date(2026, 4, 10)).interval == "1h"


def test_event_after_the_date_contributes_nothing():
    assert evaluate(_event(REF, RULES_30_7), date(2026, 4, 16)).interval is None


def test_deadline_shares_the_event_path():
    profile = _event(REF, RULES_30_7, profile_type="deadline")
    assert evaluate(profile, date(2026, 4, 5)).interval == "6h"
    assert evaluate(profile, date(2026, 4, 16)).interval is None


def test_seasonal_within_range_uses_its_rule():
    profile = _seasonal(date(2026, 6, 1), date(2026, 8, 31))
    assert evaluate(profile, date(2026, 6, 15)).interval == "1h"


def test_seasonal_outside_range_contributes_nothing():
    profile = _seasonal(date(2026, 6, 1), date(2026, 8, 31))
    assert evaluate(profile, date(2026, 5, 15)).interval is None


def test_an_inactive_profile_contributes_nothing_and_fires_nothing():
    profile = _event(REF, RULES_30_7, is_active=False)
    assert evaluate(profile, date(2026, 4, 1)) == Evaluation(None, False)
    assert evaluate(profile, date(2026, 4, 16)) == Evaluation(None, False)


def test_post_action_is_due_after_the_event():
    assert evaluate(_event(REF, RULES_30_7), date(2026, 4, 16)).post_action_due


def test_post_action_is_not_due_before_the_event():
    assert not evaluate(_event(REF, RULES_30_7), date(2026, 4, 10)).post_action_due


def test_seasonal_post_action_is_due_after_the_end():
    profile = _seasonal(date(2026, 6, 1), date(2026, 8, 31))
    assert evaluate(profile, date(2026, 9, 1)).post_action_due


# --- The edges Watcher left unpinned -----------------------------------------


@pytest.mark.parametrize(
    ("today", "interval", "due"),
    [
        (date(2026, 3, 15), None, False),  # 31 days out: no rule covers it
        (date(2026, 3, 16), "6h", False),  # days-until == 30 == days_before
        (date(2026, 4, 7), "6h", False),  # 8 days out
        (date(2026, 4, 8), "1h", False),  # days-until == 7 == days_before
        (date(2026, 4, 15), "1h", False),  # the reference date itself (days-until 0)
        (date(2026, 4, 16), None, True),  # ref + 1: silent, and the post-action fires
    ],
)
def test_event_steps_at_each_rule_boundary(today, interval, due):
    assert evaluate(_event(REF, RULES_30_7), today) == Evaluation(interval, due)


@pytest.mark.parametrize(
    ("today", "interval", "due"),
    [
        (date(2026, 5, 31), None, False),
        (date(2026, 6, 1), "1h", False),  # first day, inclusive
        (date(2026, 8, 31), "1h", False),  # last day, inclusive
        (date(2026, 9, 1), None, True),
    ],
)
def test_seasonal_range_is_inclusive_at_both_ends(today, interval, due):
    profile = _seasonal(date(2026, 6, 1), date(2026, 8, 31))
    assert evaluate(profile, today) == Evaluation(interval, due)


@pytest.mark.parametrize(
    ("today", "interval"),
    [
        (date(2026, 12, 14), None),
        (date(2026, 12, 15), "2h"),
        (date(2026, 12, 31), "2h"),
        (date(2027, 1, 1), "2h"),
        (date(2027, 1, 15), "2h"),
        (date(2027, 1, 16), None),
    ],
)
def test_a_seasonal_range_crosses_a_year_end(today, interval):
    profile = _seasonal(date(2026, 12, 15), date(2027, 1, 15), "2h")
    assert evaluate(profile, today).interval == interval


def test_dates_are_absolute_and_nothing_recurs_yearly():
    profile = _seasonal(date(2026, 6, 1), date(2026, 8, 31))
    assert evaluate(profile, date(2027, 6, 15)).interval is None


@pytest.mark.parametrize(
    ("today", "interval", "due"),
    [
        (date(2028, 2, 21), "6h", False),  # 8 days before the leap day
        (date(2028, 2, 22), "1h", False),  # 7 days: Feb 29 counts as a day
        (date(2028, 2, 29), "1h", False),  # the leap day is the reference
        (date(2028, 3, 1), None, True),
    ],
)
def test_a_leap_day_counts(today, interval, due):
    profile = _event(date(2028, 2, 29), RULES_30_7)
    assert evaluate(profile, today) == Evaluation(interval, due)


@pytest.mark.parametrize(
    ("now", "today"),
    [
        (datetime(2026, 4, 15, 23, 59, 59, 999999, tzinfo=UTC), date(2026, 4, 15)),
        (datetime(2026, 4, 16, 0, 0, 0, tzinfo=UTC), date(2026, 4, 16)),
        # 17:00 at UTC-7 is already midnight UTC: the UTC day decides.
        (datetime(2026, 4, 15, 17, 0, tzinfo=timezone(timedelta(hours=-7))), date(2026, 4, 16)),
    ],
)
def test_today_is_the_utc_calendar_day(now, today):
    assert utc_today(now) == today


def test_utc_today_refuses_a_naive_datetime():
    with pytest.raises(ValueError, match="timezone"):
        utc_today(datetime(2026, 4, 15, 12, 0))


def test_the_smallest_covering_rule_wins_whatever_the_order():
    profile = _event(REF, list(reversed(RULES_30_7)))
    assert evaluate(profile, date(2026, 4, 10)).interval == "1h"


def test_a_profile_with_no_rules_only_fires():
    profile = _event(REF, [], post_action="deactivate")
    assert evaluate(profile, date(2026, 4, 15)) == Evaluation(None, False)
    assert evaluate(profile, date(2026, 4, 16)) == Evaluation(None, True)


def test_a_fired_profile_is_not_due_again():
    profile = _event(REF, RULES_30_7, fired_at=datetime(2026, 4, 16, 0, 5, tzinfo=UTC))
    assert evaluate(profile, date(2026, 4, 17)) == Evaluation(None, False)


def test_window_end_is_the_reference_date_or_the_range_end():
    assert window_end(_event(REF, RULES_30_7)) == REF
    assert window_end(_seasonal(date(2026, 6, 1), date(2026, 8, 31))) == date(2026, 8, 31)


# --- Validation (write time, and the job's skip rule) ------------------------


def test_a_valid_event_has_no_errors():
    assert profile_errors(_event(REF, RULES_30_7)) == []


def test_a_valid_seasonal_has_no_errors():
    assert profile_errors(_seasonal(date(2026, 6, 1), date(2026, 8, 31))) == []


def _paths(profile: TemporalProfile) -> list[str]:
    return [path for path, _message in profile_errors(profile)]


@pytest.mark.parametrize(
    ("kwargs", "path"),
    [
        ({"profile_type": "weekly"}, "profile_type"),
        ({"post_action": "notify"}, "post_action"),
        ({"reference_date": None}, "reference_date"),
        ({"date_range_start": date(2026, 4, 1)}, "date_range_start"),
        ({"date_range_end": date(2026, 4, 30)}, "date_range_end"),
        ({"rules": "6h"}, "rules"),
        ({"rules": [{"days_before": 7}]}, "rules/0/interval"),
        ({"rules": [{"interval": "1h"}]}, "rules/0/days_before"),
        ({"rules": [{"days_before": -1, "interval": "1h"}]}, "rules/0/days_before"),
        ({"rules": [{"days_before": 1.5, "interval": "1h"}]}, "rules/0/days_before"),
        ({"rules": [{"days_before": True, "interval": "1h"}]}, "rules/0/days_before"),
        ({"rules": [{"days_before": 7, "interval": "1 hour"}]}, "rules/0/interval"),
        ({"rules": [{"days_before": 7, "interval": "0h"}]}, "rules/0/interval"),
        ({"rules": [{"days_before": 7, "interval": 6}]}, "rules/0/interval"),
        ({"rules": [{"days_before": 7, "interval": "1h", "note": "x"}]}, "rules/0"),
        ({"rules": ["1h"]}, "rules/0"),
        (
            {"rules": [{"days_before": 7, "interval": "1h"}, {"days_before": 7, "interval": "2h"}]},
            "rules/1/days_before",
        ),
    ],
)
def test_an_event_is_refused_with_a_path(kwargs, path):
    base = {
        "profile_type": "event",
        "reference_date": REF,
        "rules": RULES_30_7,
        "post_action": "deactivate",
    }
    assert path in _paths(TemporalProfile(**{**base, **kwargs}))


@pytest.mark.parametrize(
    ("kwargs", "path"),
    [
        ({"date_range_start": None}, "date_range_start"),
        ({"date_range_end": None}, "date_range_end"),
        ({"date_range_start": date(2026, 9, 1)}, "date_range_end"),  # start after end
        ({"reference_date": REF}, "reference_date"),
        ({"rules": []}, "rules"),
        ({"rules": [{"interval": "1h"}, {"interval": "2h"}]}, "rules"),
        ({"rules": [{"days_before": 3, "interval": "1h"}]}, "rules/0/days_before"),
    ],
)
def test_a_seasonal_is_refused_with_a_path(kwargs, path):
    base = {
        "profile_type": "seasonal",
        "date_range_start": date(2026, 6, 1),
        "date_range_end": date(2026, 8, 31),
        "rules": [{"interval": "1h"}],
        "post_action": "deactivate",
    }
    assert path in _paths(TemporalProfile(**{**base, **kwargs}))


def test_a_single_day_season_is_valid():
    assert profile_errors(_seasonal(date(2026, 6, 1), date(2026, 6, 1))) == []


@pytest.mark.parametrize("interval", ["3651d", "315360001s", "9" * 40 + "d"])
def test_an_interval_past_ten_years_is_refused(interval):
    """CR 8: past the ceiling it is not a cadence - Watcher's timedelta overflows,
    and a long digit run cannot fit ``resolved_interval``'s 32 characters."""
    profile = _event(REF, [{"days_before": 7, "interval": interval}])
    assert "rules/0/interval" in _paths(profile)


def test_ten_years_exactly_is_accepted():
    assert profile_errors(_event(REF, [{"days_before": 7, "interval": "3650d"}])) == []
