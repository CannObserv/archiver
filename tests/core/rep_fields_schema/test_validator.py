"""Tests for rep_fields_schema validator."""

from src.core.rep_fields_schema.validator import (
    validate_rep_fields,
    validate_rep_fields_against_spec,
)

# --- validate_rep_fields ---


def test_valid_bag_returns_ok():
    """Valid two-namespace bag passes shape validation."""
    ok, errors = validate_rep_fields({"org": {"acronym": "wslcb"}, "event": {"year": "2025"}})
    assert ok is True
    assert errors == []


def test_three_level_nesting_rejected():
    """Inner object value that is itself a dict violates the scalar-leaf constraint."""
    ok, errors = validate_rep_fields({"org": {"acronym": {"deep": "x"}}})
    assert ok is False
    assert len(errors) > 0


def test_uppercase_top_level_rejected():
    """Top-level key 'Org' does not match ^[a-z][a-z0-9_]*$ pattern."""
    ok, errors = validate_rep_fields({"Org": {"acronym": "x"}})
    assert ok is False
    assert len(errors) > 0


# --- validate_rep_fields_against_spec ---


def test_required_fields_all_present():
    """All required fields resolve to non-null values → ok."""
    ok, errors = validate_rep_fields_against_spec(
        {"org": {"acronym": "x"}}, ["org.acronym"]
    )
    assert ok is True
    assert errors == []


def test_required_field_missing():
    """Empty bag + required field → ok=False, error path contains org/acronym."""
    ok, errors = validate_rep_fields_against_spec({}, ["org.acronym"])
    assert ok is False
    assert any("org/acronym" in e["path"] for e in errors)


def test_required_field_present_but_null():
    """Field present but null counts as missing."""
    ok, errors = validate_rep_fields_against_spec(
        {"org": {"acronym": None}}, ["org.acronym"]
    )
    assert ok is False
    assert len(errors) > 0


def test_malformed_required_fields_entry():
    """'bareword' (no dot) → ok=False, error explains malformed."""
    ok, errors = validate_rep_fields_against_spec({}, ["bareword"])
    assert ok is False
    assert any("malformed" in e["message"] for e in errors)
