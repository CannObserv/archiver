"""Tests for the create_rep_spec core tool."""

from __future__ import annotations

import pytest

from src.core.models import RepSpec
from src.core.tools.create_rep_spec import (
    InvalidRepSpecError,
    create_rep_spec,
)


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        "required_fields": ["info_item.slug"],
        "object_options": {"storage_class": "STANDARD"},
    }


@pytest.mark.asyncio
async def test_create_rep_spec_persists_row_with_schema_version_1(session):
    spec = await create_rep_spec(
        session, provider="gcs", name="board-meetings-gcs", document=_gcs_doc()
    )
    await session.commit()

    fetched = await session.get(RepSpec, spec.rep_spec_id)
    assert fetched is not None
    assert fetched.provider == "gcs"
    assert fetched.name == "board-meetings-gcs"
    assert fetched.schema_version == 1
    assert fetched.document["path_template"].startswith("archive/")


@pytest.mark.asyncio
async def test_create_rep_spec_rejects_missing_envelope_field(session):
    bad = _gcs_doc()
    del bad["path_template"]
    with pytest.raises(InvalidRepSpecError) as exc:
        await create_rep_spec(session, provider="gcs", name="x", document=bad)
    assert any("path_template" in e["message"] for e in exc.value.errors)


@pytest.mark.asyncio
async def test_create_rep_spec_rejects_unknown_provider(session):
    bad = _gcs_doc() | {"provider": "s3"}
    with pytest.raises(InvalidRepSpecError) as exc:
        await create_rep_spec(session, provider="s3", name="x", document=bad)
    assert any("provider" in e["path"] for e in exc.value.errors)


@pytest.mark.asyncio
async def test_create_rep_spec_rejects_invalid_provider_sub_schema(session):
    bad = _gcs_doc()
    bad["object_options"] = {"storage_class": "BANANA"}
    with pytest.raises(InvalidRepSpecError) as exc:
        await create_rep_spec(session, provider="gcs", name="x", document=bad)
    assert any("object_options" in e["path"] for e in exc.value.errors)


@pytest.mark.asyncio
async def test_create_rep_spec_provider_mismatch_with_document_is_rejected(session):
    """If the request says provider=gcs but the document says provider=gdrive, reject."""
    bad = _gcs_doc() | {"provider": "gdrive"}
    with pytest.raises(InvalidRepSpecError) as exc:
        await create_rep_spec(session, provider="gcs", name="x", document=bad)
    mismatch_errors = [e for e in exc.value.errors if e["path"] == "/provider"]
    assert mismatch_errors, "expected an error at path /provider"
    assert "'gcs'" in mismatch_errors[0]["message"]
    assert "'gdrive'" in mismatch_errors[0]["message"]
