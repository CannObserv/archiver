"""The v1 SourceSpec schema declares the cascade contract at the top level."""

import json
from pathlib import Path

from src.core.source_spec_schema.validator import validate_source_spec

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "src/core/source_spec_schema/v1.json").read_text()
)


def test_top_level_description_states_cascade_contract():
    desc = SCHEMA.get("description", "")
    # Must explicitly call out the fetch-group invariant and the
    # "no chaining" rule. The wording can drift, but these keywords
    # are what authoring agents will grep for.
    assert "fetch group" in desc.lower()
    assert "primary" in desc.lower()
    assert "no chaining" in desc.lower() or "not chained" in desc.lower()


def test_existing_extraction_validation_still_works():
    """Top-level description must not break existing schema validation."""
    ok, errs = validate_source_spec(
        {
            "schema_version": 1,
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        }
    )
    assert ok, errs
