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


def test_jsonpath_spec_valid(validator):
    """co-core 0.38 honours ``jsonpath`` on JSON (cannobserv#354, #356)."""
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "jsonpath", "selector": "$.data[*].value"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_algorithm_no_extractor_honours_rejected(validator):
    """No extractor honours ``regex`` (cannobserv#523, #317)."""
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "regex", "selector": "Agenda.*"},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


@pytest.mark.parametrize(
    "extraction",
    [
        {"algorithm": "jsonpath"},
        {"algorithm": "jsonpath", "selector": ""},
        {"algorithm": "jsonpath", "selector": "$.a", "ignore_selectors": [".ad"]},
    ],
    ids=["no-selector", "empty-selector", "ignore-selectors"],
)
def test_jsonpath_refusals_the_schema_can_see(validator, extraction):
    """co-core refuses each whatever the body (#356 D2); syntax stays co-core's, at /extraction."""
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"schema_version": 1, "extraction": extraction, "fingerprint": {}})


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


def _with_ignore(algorithm: str, ignore_selectors) -> dict:
    extraction = {"algorithm": algorithm, "ignore_selectors": ignore_selectors}
    if algorithm != "full_page":
        extraction["selector"] = "//main" if algorithm == "xpath" else "main"
    return {"schema_version": 1, "extraction": extraction, "fingerprint": {}}


@pytest.mark.parametrize("algorithm", ["css", "xpath", "full_page"])
def test_ignore_selectors_valid_under_every_html_algorithm(validator, algorithm):
    """co-core 0.38 removes them before the selection under all three (cannobserv#570, #378)."""
    validator.validate(_with_ignore(algorithm, [".timestamp", "#ad-slot"]))


@pytest.mark.parametrize(
    "ignore_selectors",
    [
        [],  # minItems: [] extracts as an absent key does, but moves spec1:
        [""],
        ["   "],
        [".ok", 1],
        ".timestamp",
        None,
    ],
)
def test_malformed_ignore_selectors_rejected(validator, ignore_selectors):
    """What co-core's translator refuses, plus ``[]``: a second spelling of "none"."""
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(_with_ignore("css", ignore_selectors))
