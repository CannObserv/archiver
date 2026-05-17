"""SourceRevisionCapturedEvent payload tests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.core.changes.payloads import SourceRevisionCapturedEvent

SAMPLE_BINDING = {"info_item_id": "01HZZ000000000000000000003", "role": None}


def _sample() -> dict:
    return {
        "event_type": "source_revision_captured",
        "occurred_at": "2026-05-08T12:00:00+00:00",
        "info_source_id": "01HZZ000000000000000000001",
        "source_revision_id": "01HZZ000000000000000000002",
        "content_fingerprint": "sha256:" + "a" * 64,
        "bindings": [SAMPLE_BINDING],
    }


def test_round_trip():
    ev = SourceRevisionCapturedEvent.model_validate(_sample())
    dumped = ev.model_dump(mode="json")
    assert dumped["event_type"] == "source_revision_captured"
    assert dumped["info_source_id"] == "01HZZ000000000000000000001"
    assert dumped["bindings"] == [SAMPLE_BINDING]


def test_round_trip_through_json():
    ev = SourceRevisionCapturedEvent.model_validate(_sample())
    j = ev.model_dump_json()
    parsed = SourceRevisionCapturedEvent.model_validate_json(j)
    assert parsed == ev


def test_event_type_literal_locked():
    bad = _sample() | {"event_type": "anything_else"}
    with pytest.raises(ValidationError):
        SourceRevisionCapturedEvent.model_validate(bad)


def test_extra_fields_rejected():
    bad = _sample() | {"junk": True}
    with pytest.raises(ValidationError):
        SourceRevisionCapturedEvent.model_validate(bad)


def test_empty_bindings_allowed():
    """Watcher may produce a revision before any item binds — empty list valid."""
    minimal = _sample() | {"bindings": []}
    ev = SourceRevisionCapturedEvent.model_validate(minimal)
    assert ev.bindings == []


def test_default_event_type():
    """event_type can be omitted; defaults to the literal."""
    minimal = {k: v for k, v in _sample().items() if k != "event_type"}
    ev = SourceRevisionCapturedEvent.model_validate(minimal)
    assert ev.event_type == "source_revision_captured"


def test_construct_with_datetime_obj():
    """occurred_at accepts a datetime instance, not just a string."""
    payload = _sample() | {"occurred_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC)}
    ev = SourceRevisionCapturedEvent.model_validate(payload)
    assert ev.occurred_at.tzinfo is not None


def test_schema_version_defaults_to_1():
    """Producer omits schema_version; model defaults to 1 and includes it on dump."""
    ev = SourceRevisionCapturedEvent.model_validate(_sample())
    assert ev.schema_version == 1
    assert ev.model_dump(mode="json")["schema_version"] == 1


def test_schema_version_is_writable_for_forward_versions():
    """The model accepts forward version numbers on the wire (e.g. 2) without
    raising. It does NOT magically know how to parse a v2 shape — consumers
    must gate destructuring on ``schema_version`` themselves before assuming
    a shape. This test only asserts the field is a writable int."""
    payload = _sample() | {"schema_version": 2}
    ev = SourceRevisionCapturedEvent.model_validate(payload)
    assert ev.schema_version == 2


def test_schema_version_round_trips_through_json_for_non_default_value():
    """A non-default ``schema_version`` survives serialize → parse intact, so a
    future bump cannot be silently normalized away by Pydantic."""
    payload = _sample() | {"schema_version": 7}
    ev = SourceRevisionCapturedEvent.model_validate(payload)
    j = ev.model_dump_json()
    parsed = SourceRevisionCapturedEvent.model_validate_json(j)
    assert parsed.schema_version == 7
