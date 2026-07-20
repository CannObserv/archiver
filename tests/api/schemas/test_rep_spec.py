"""Schema-level tests for RepSpecCreate/RepSpecOut."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.api.schemas.rep_spec import RepSpecCreate, RepSpecOut


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.date}.html",
        "required_fields": ["info_item.slug", "source_revision.date"],
        "object_options": {"storage_class": "STANDARD"},
    }


def test_rep_spec_create_accepts_minimum_fields():
    body = RepSpecCreate(provider="gcs", name="board-meetings-gcs", document=_gcs_doc())
    assert body.provider == "gcs"
    assert body.name == "board-meetings-gcs"
    assert body.document["provider"] == "gcs"


def test_rep_spec_create_forbids_extra_fields():
    with pytest.raises(ValidationError):
        RepSpecCreate(
            provider="gcs",
            name="x",
            document=_gcs_doc(),
            schema_version=1,  # type: ignore[call-arg]  -- intentionally extra
        )


def test_rep_spec_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        RepSpecCreate(provider="gcs", name="", document=_gcs_doc())


def test_rep_spec_create_rejects_empty_provider():
    with pytest.raises(ValidationError):
        RepSpecCreate(provider="", name="x", document=_gcs_doc())


def test_rep_spec_out_round_trip():
    out = RepSpecOut(
        rep_spec_id="01J0000000000000000000000A",
        provider="gcs",
        name="x",
        schema_version=1,
        document=_gcs_doc(),
        created_at="2026-05-11T00:00:00Z",  # pydantic accepts ISO 8601
        updated_at=None,  # required-but-nullable: null means never edited (#83)
    )
    assert out.rep_spec_id == "01J0000000000000000000000A"
    assert out.provider == "gcs"
    assert out.name == "x"
    assert out.schema_version == 1
    assert out.document == _gcs_doc()
    assert isinstance(out.created_at, datetime)
    assert out.updated_at is None
