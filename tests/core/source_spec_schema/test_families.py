"""Tests for the algorithm-family taxonomy."""

import pytest

from src.core.source_spec_schema.families import (
    ALGORITHM_FAMILIES,
    UnknownAlgorithmError,
    family_for,
)


def test_html_text_family_members():
    assert family_for("css") == "html_text"
    assert family_for("xpath") == "html_text"
    assert family_for("regex") == "html_text"
    assert family_for("full_page") == "html_text"


def test_json_family_member():
    assert family_for("jsonpath") == "json"


def test_unknown_algorithm_raises():
    with pytest.raises(UnknownAlgorithmError):
        family_for("xqilla")


def test_taxonomy_covers_every_algorithm_in_the_schema():
    """Every algorithm enumerated in v1.json must have a family.

    Guards against silent drift: adding a new algorithm to the JSON schema
    without classifying it here would make bind_info_source raise
    UnknownAlgorithmError on every fragment binding using it.
    """
    import json
    from pathlib import Path

    schema = json.loads(
        (Path(__file__).resolve().parents[3] / "src/core/source_spec_schema/v1.json").read_text()
    )
    schema_algorithms = set(schema["properties"]["extraction"]["properties"]["algorithm"]["enum"])
    assert schema_algorithms == set(ALGORITHM_FAMILIES.keys())
