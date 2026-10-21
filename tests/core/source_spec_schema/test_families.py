"""Tests for the algorithm-family taxonomy."""

import json
from pathlib import Path

import pytest

from src.core.source_spec_schema.families import (
    ALGORITHM_FAMILIES,
    UnknownAlgorithmError,
    families_of,
    family_for,
)


def test_html_text_family_members():
    assert family_for("css") == "html_text"
    assert family_for("xpath") == "html_text"


def test_jsonpath_is_the_json_family():
    """co-core 0.38 honours ``jsonpath`` on JSON bodies (cannobserv#354, #356)."""
    assert family_for("jsonpath") == "json"


def test_full_page_is_family_neutral():
    """``full_page`` honours every media type co-core dispatches, JSON included (#356 D1)."""
    assert family_for("full_page") is None


def test_refused_algorithm_has_no_family():
    """No extractor honours ``regex`` (cannobserv#523, #317), so the schema drops it."""
    with pytest.raises(UnknownAlgorithmError):
        family_for("regex")


@pytest.mark.parametrize(
    ("algorithms", "families"),
    [
        (["css", "xpath"], {"html_text"}),
        (["full_page", "jsonpath"], {"json"}),
        (["jsonpath", "full_page", "css"], {"json", "html_text"}),
        (["full_page"], set()),
    ],
)
def test_families_of_drops_the_neutral_algorithm(algorithms, families):
    assert families_of(algorithms) == families


def test_families_of_raises_on_an_unknown_algorithm():
    with pytest.raises(UnknownAlgorithmError):
        families_of(["css", "regex"])


def test_unknown_algorithm_raises():
    with pytest.raises(UnknownAlgorithmError) as exc_info:
        family_for("xqilla")
    assert isinstance(exc_info.value.__cause__, KeyError)


def test_taxonomy_covers_every_algorithm_in_the_schema():
    """Every algorithm enumerated in v1.json must have a family.

    Guards against silent drift: adding a new algorithm to the JSON schema
    without classifying it here would make bind_info_source raise
    UnknownAlgorithmError on every fragment binding using it.
    """
    schema = json.loads(
        (Path(__file__).resolve().parents[3] / "src/core/source_spec_schema/v1.json").read_text()
    )
    schema_algorithms = set(schema["properties"]["extraction"]["properties"]["algorithm"]["enum"])
    assert schema_algorithms == set(ALGORITHM_FAMILIES.keys())
