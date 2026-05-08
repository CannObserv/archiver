"""SourceSpec v1 schema shape tests (validator wrapper is Task B2)."""

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


def test_root_full_page_valid(validator):
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_root_css_with_selector_valid(validator):
    """A root source can use a CSS selector for its extraction.

    Root vs. fragment is distinguished by presence of target.url, not the
    extraction.algorithm choice.
    """
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_root_missing_url_rejected(validator):
    doc = {
        "schema_version": 1,
        "target": {},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_root_css_missing_selector_rejected(validator):
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "css"},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_fragment_no_target_valid(validator):
    """Fragment SourceSpec: no target field → schema allows it (XOR enforced at DB)."""
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_extra_top_level_property_rejected(validator):
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
        "junk": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_url_canonicalization_strip_query_keys_valid(validator):
    """target.url_canonicalization.strip_query_keys is an optional list of strings."""
    doc = {
        "schema_version": 1,
        "target": {
            "url": "https://example.com/p",
            "url_canonicalization": {"strip_query_keys": ["utm_source", "utm_medium"]},
        },
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }
    validator.validate(doc)
