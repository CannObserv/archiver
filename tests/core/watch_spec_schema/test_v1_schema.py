"""WatchSpec v1 schema shape + the boundaries its description has to state."""

import json
from pathlib import Path

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "src/core/watch_spec_schema/v1.json").read_text()
)


def test_only_schema_version_is_required():
    assert SCHEMA["required"] == ["schema_version"]


def test_the_document_is_cadence_only():
    """active/paused is the sibling column watch_active, not a key in here.

    A policy document shared across items could not carry per-item pause state,
    and nested in an untyped dict the three-state distinction had no schema
    guarantee — co-core's RegistryAnnouncementState accepts a nested ``active``
    silently while its own envelope field stays None.
    """
    assert "active" not in SCHEMA["properties"]
    assert set(SCHEMA["properties"]) == {"schema_version", "interval"}


def test_additional_properties_are_closed():
    assert SCHEMA["additionalProperties"] is False


def test_description_states_the_fetch_policy_boundary():
    """WatchSpec is per-item cadence; content.fetch-policy is per-host spacing.

    Both answer "how often do we hit things" and will attract merge proposals.
    The wording can drift; these keywords are what the next reader greps for.
    """
    desc = SCHEMA.get("description", "").lower()
    assert "fetch-policy" in desc or "fetch policy" in desc
    assert "per-item" in desc
    assert "per-host" in desc


def test_description_points_at_where_active_actually_lives():
    desc = SCHEMA.get("description", "").lower()
    assert "watch_active" in desc


def test_description_states_that_absent_interval_means_consumer_default():
    interval = SCHEMA["properties"]["interval"]
    desc = (SCHEMA.get("description", "") + interval.get("description", "")).lower()
    assert "default" in desc
