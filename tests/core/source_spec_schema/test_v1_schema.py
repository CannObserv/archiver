"""SourceSpec v1 schema shape tests."""

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "src/core/source_spec_schema/v1.json"


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema):
    return jsonschema.Draft202012Validator(schema)


def test_full_page_spec_valid(validator):
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_css_spec_valid(validator):
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_xpath_spec_valid(validator):
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "xpath", "selector": "//item/title"},
        "fingerprint": {},
    }
    validator.validate(doc)


@pytest.mark.parametrize(
    ("algorithm", "selector"), [("jsonpath", "$.data[*].value"), ("regex", "Agenda.*")]
)
def test_algorithm_no_extractor_honours_rejected(validator, algorithm, selector):
    """co-core 0.32 refuses ``regex`` and ``jsonpath`` (cannobserv#523, #317).

    A spec that validates here must reach an extractor that honours it; ``jsonpath``
    returns with cannobserv#354.
    """
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": algorithm, "selector": selector},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_css_missing_selector_rejected(validator):
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "css"},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_target_field_rejected(validator):
    """target is no longer part of the spec — URL lives on InfoSource directly."""
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_extra_top_level_property_rejected(validator):
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
        "junk": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_xpath_empty_selector_rejected(validator):
    """co-core refuses an empty xpath (cannobserv#523); an empty css selector is the whole page."""
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "xpath", "selector": ""},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_css_empty_selector_still_valid(validator):
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": ""},
        "fingerprint": {},
    }
    validator.validate(doc)
