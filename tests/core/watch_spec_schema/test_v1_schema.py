"""WatchSpec v1 schema shape + the boundary its description has to state."""

import json
from pathlib import Path

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "src/core/watch_spec_schema/v1.json").read_text()
)


def test_only_schema_version_and_active_are_required():
    assert set(SCHEMA["required"]) == {"schema_version", "active"}


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


def test_description_states_that_absent_interval_means_consumer_default():
    interval = SCHEMA["properties"]["interval"]
    desc = (SCHEMA.get("description", "") + interval.get("description", "")).lower()
    assert "default" in desc
