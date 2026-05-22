"""Tests that every field in entity Out schemas has an OpenAPI description.

Descriptions appear in /openapi.json and are consumed by API clients and agents.
Tests inspect model_json_schema() directly — no HTTP or DB required.
"""

from src.api.schemas.info_item import InfoItemOut
from src.api.schemas.info_source import InfoSourceOut
from src.api.schemas.rep_spec import RepSpecOut
from src.api.schemas.source_revision import SourceRevisionOut


def _fields_without_description(model_cls) -> list[str]:
    schema = model_cls.model_json_schema()
    return [
        name
        for name, field_schema in schema.get("properties", {}).items()
        if "description" not in field_schema
    ]


def test_info_item_out_all_fields_have_descriptions():
    missing = _fields_without_description(InfoItemOut)
    assert missing == [], f"Fields missing descriptions in InfoItemOut: {missing}"


def test_info_source_out_all_fields_have_descriptions():
    missing = _fields_without_description(InfoSourceOut)
    assert missing == [], f"Fields missing descriptions in InfoSourceOut: {missing}"


def test_rep_spec_out_all_fields_have_descriptions():
    missing = _fields_without_description(RepSpecOut)
    assert missing == [], f"Fields missing descriptions in RepSpecOut: {missing}"


def test_source_revision_out_all_fields_have_descriptions():
    missing = _fields_without_description(SourceRevisionOut)
    assert missing == [], f"Fields missing descriptions in SourceRevisionOut: {missing}"
