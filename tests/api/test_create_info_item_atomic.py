"""Tests for atomic InfoItem creation (v2 shape).

Covers:
- name-only create (no source, no assignments) → empty arrays
- create with valid initial_url + initial_source_specs → info_item_sources populated
- create with rep_fields + initial_rep_spec_assignments → assignments created
- create with bad source_specs → 422, no InfoItem persisted
- create with non-existent rep_spec_id → 404, no InfoItem persisted
- create with rep_fields that doesn't satisfy required_fields → 422, no InfoItem persisted
- create with initial_url but no initial_source_specs → 422 (validator)
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from src.core.models import InfoItem, InfoItemRepSpec, InfoItemSource, InfoSource, RepSpec

HEADERS = {"X-API-Key": "test-secret-key"}

VALID_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "full_page"},
    "fingerprint": {},
}


@pytest.fixture
async def rep_spec_row(session) -> RepSpec:
    """Insert a minimal RepSpec for assignment tests."""
    rs = RepSpec(
        provider="gcs",
        name="test-rep-spec",
        schema_version=1,
        document={
            "provider": "gcs",
            "credentials_alias": "default",
            "path_template": "gs://bucket/{gcs.object_name}",
            "required_fields": ["gcs.object_name"],
        },
    )
    session.add(rs)
    await session.flush()
    return rs


# ---------------------------------------------------------------------------
# Happy path — name only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_name_only_returns_empty_arrays(client):
    """No source, no assignments → empty lists, rep_fields={}."""
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={"name": "name-only"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "name-only"
    assert body["info_item_sources"] == []
    assert body["info_item_rep_specs"] == []
    assert body["rep_fields"] == {}


# ---------------------------------------------------------------------------
# Happy path — with initial_url + initial_source_specs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_with_initial_url_populates_info_item_sources(client, session):
    """Valid initial_url + source_specs → one info_item_sources entry."""
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "with-source",
            "initial_url": "https://example.com/licenses",
            "initial_source_specs": [VALID_SPEC],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "with-source"
    assert len(body["info_item_sources"]) == 1
    src_out = body["info_item_sources"][0]
    assert "role" not in src_out
    assert len(src_out["info_source_id"]) == 26  # ULID

    # DB round-trip: exactly one InfoSource + one InfoItemSource
    item_id = body["info_item_id"]
    binding_count = await session.scalar(
        select(func.count(InfoItemSource.info_source_id)).where(
            InfoItemSource.info_item_id == item_id
        )
    )
    assert binding_count == 1

    # InfoSource row should exist with the canonicalized URL
    binding = (
        await session.execute(select(InfoItemSource).where(InfoItemSource.info_item_id == item_id))
    ).scalar_one()
    info_source = (
        await session.execute(
            select(InfoSource).where(InfoSource.info_source_id == binding.info_source_id)
        )
    ).scalar_one()
    assert info_source.url == "https://example.com/licenses"


# ---------------------------------------------------------------------------
# Happy path — with rep_spec assignments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_with_rep_spec_assignment(client, session, rep_spec_row):
    """Valid assignment → info_item_rep_specs populated."""
    rep_spec_id = str(rep_spec_row.rep_spec_id)
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "with-rep-spec",
            "rep_fields": {"gcs": {"object_name": "co/active-licenses"}},
            "initial_rep_spec_assignments": [{"rep_spec_id": rep_spec_id}],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["info_item_rep_specs"]) == 1
    airs_out = body["info_item_rep_specs"][0]
    assert airs_out["rep_spec_id"] == rep_spec_id
    assert airs_out["deactivated_at"] is None
    assert airs_out["public_url"] is None

    item_id = body["info_item_id"]
    airs_count = await session.scalar(
        select(func.count(InfoItemRepSpec.id)).where(InfoItemRepSpec.info_item_id == item_id)
    )
    assert airs_count == 1


@pytest.mark.asyncio
async def test_create_with_explicit_activated_at(client, session, rep_spec_row):
    """activated_at supplied → stored verbatim."""
    rep_spec_id = str(rep_spec_row.rep_spec_id)
    activated_at = "2026-05-01T00:00:00.000000Z"
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "with-activated-at",
            "rep_fields": {"gcs": {"object_name": "co/active-licenses"}},
            "initial_rep_spec_assignments": [
                {"rep_spec_id": rep_spec_id, "activated_at": activated_at}
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    airs_out = body["info_item_rep_specs"][0]
    stored = datetime.fromisoformat(airs_out["activated_at"].replace("Z", "+00:00"))
    assert stored == datetime(2026, 5, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_with_bad_source_specs_returns_422_no_rows(client, session):
    """Invalid spec element (css without selector) → 422; no InfoItem persisted."""
    bad_spec = {
        "schema_version": 1,
        "extraction": {"algorithm": "css"},  # missing selector
        "fingerprint": {},
    }
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "should-not-exist",
            "initial_url": "https://example.com/bad",
            "initial_source_specs": [bad_spec],
        },
    )
    assert response.status_code == 422

    item_count = await session.scalar(
        select(func.count(InfoItem.info_item_id)).where(InfoItem.name == "should-not-exist")
    )
    assert item_count == 0


@pytest.mark.asyncio
async def test_create_with_initial_url_but_no_source_specs_returns_422(client):
    """initial_url without initial_source_specs → 422 (Pydantic validator at schema layer)."""
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={"name": "url-without-specs", "initial_url": "https://example.com/page"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_with_nonexistent_rep_spec_returns_404_no_rows(client, session):
    """rep_spec_id that doesn't exist → 404; no InfoItem persisted."""
    fake_id = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "should-not-exist-2",
            "initial_rep_spec_assignments": [{"rep_spec_id": fake_id}],
        },
    )
    assert response.status_code == 404

    item_count = await session.scalar(
        select(func.count(InfoItem.info_item_id)).where(InfoItem.name == "should-not-exist-2")
    )
    assert item_count == 0


@pytest.mark.asyncio
async def test_create_with_rep_fields_missing_required_returns_422_no_rows(
    client, session, rep_spec_row
):
    """rep_fields doesn't satisfy required_fields → 422; no InfoItem persisted."""
    rep_spec_id = str(rep_spec_row.rep_spec_id)
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "should-not-exist-3",
            "rep_fields": {},
            "initial_rep_spec_assignments": [{"rep_spec_id": rep_spec_id}],
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"].startswith("rep_fields does not satisfy RepSpec")
    assert detail["data"]["rep_spec_id"] == rep_spec_id
    assert len(detail["errors"]) >= 1
    assert all(err["code"] == "rep_fields_incomplete" for err in detail["errors"])

    item_count = await session.scalar(
        select(func.count(InfoItem.info_item_id)).where(InfoItem.name == "should-not-exist-3")
    )
    assert item_count == 0
