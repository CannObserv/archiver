"""Tests for top-level /rep-specs endpoints.

Covers:
- POST /rep-specs (201 happy path + 422 validation failures)
- GET /rep-specs/{rep_spec_id} (200 + 404)
- GET /rep-specs (Page envelope, ?provider= filter, pagination probe)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ulid import ULID

from src.core.models import InfoItem, InfoItemRepSpec

HEADERS = {"X-API-Key": "test-secret-key"}


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        "required_fields": ["info_item.slug"],
        "object_options": {"storage_class": "STANDARD"},
    }


def _gdrive_doc() -> dict:
    return {
        "provider": "gdrive",
        "credentials_alias": "gdrive-prod",
        "path_template": "{info_item.slug}/{source_revision.id}",
        "required_fields": ["info_item.slug"],
        "object_options": {},
    }


# ---------------------------------------------------------------------------
# POST /api/v1/rep-specs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_returns_201_with_server_assigned_id_and_schema_version(client):
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "board-meetings", "document": _gcs_doc()},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["rep_spec_id"]) == 26
    assert body["provider"] == "gcs"
    assert body["name"] == "board-meetings"
    assert body["schema_version"] == 1
    assert body["document"]["path_template"].startswith("archive/")


@pytest.mark.asyncio
async def test_post_returns_422_on_missing_envelope_field(client):
    bad = _gcs_doc()
    del bad["path_template"]
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "x", "document": bad},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["kind"] == "schema"
    assert detail["message"] == "invalid rep_spec"
    assert any("path_template" in e["message"] for e in detail["errors"])


@pytest.mark.asyncio
async def test_post_returns_422_on_unknown_provider(client):
    bad = _gcs_doc() | {"provider": "s3"}
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "s3", "name": "x", "document": bad},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_returns_422_on_bad_provider_sub_schema(client):
    bad = _gcs_doc()
    bad["object_options"] = {"storage_class": "BANANA"}
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "x", "document": bad},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "schema"
    assert detail["message"] == "invalid rep_spec"
    assert any("object_options" in e["path"] for e in detail["errors"])


@pytest.mark.asyncio
async def test_post_returns_422_on_provider_mismatch(client):
    bad = _gdrive_doc()  # document says gdrive
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "x", "document": bad},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "schema"
    assert detail["message"] == "invalid rep_spec"
    mismatch_errors = [e for e in detail["errors"] if e["path"] == "/provider"]
    assert mismatch_errors, "expected an error at path /provider"
    assert "'gcs'" in mismatch_errors[0]["message"]
    assert "'gdrive'" in mismatch_errors[0]["message"]


@pytest.mark.asyncio
async def test_post_rejects_extra_fields(client):
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={
            "provider": "gcs",
            "name": "x",
            "document": _gcs_doc(),
            "schema_version": 1,  # forbidden
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/rep-specs/{rep_spec_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_200_for_existing(client):
    created = (
        await client.post(
            "/api/v1/rep-specs",
            headers=HEADERS,
            json={"provider": "gcs", "name": "n", "document": _gcs_doc()},
        )
    ).json()
    resp = await client.get(f"/api/v1/rep-specs/{created['rep_spec_id']}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["rep_spec_id"] == created["rep_spec_id"]


@pytest.mark.asyncio
async def test_get_returns_404_for_unknown_id(client):
    resp = await client.get("/api/v1/rep-specs/01J0000000000000000000000Z", headers=HEADERS)
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "RepSpec not found"


@pytest.mark.asyncio
async def test_get_returns_422_for_malformed_ulid(client):
    resp = await client.get("/api/v1/rep-specs/not-a-ulid", headers=HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/rep-specs (list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_page_envelope(client):
    for i in range(3):
        await client.post(
            "/api/v1/rep-specs",
            headers=HEADERS,
            json={"provider": "gcs", "name": f"n{i}", "document": _gcs_doc()},
        )
    resp = await client.get("/api/v1/rep-specs", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "has_more", "limit", "offset"}
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert body["has_more"] is False
    assert len(body["items"]) >= 3


@pytest.mark.asyncio
async def test_list_filters_by_provider(client):
    await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "n-gcs", "document": _gcs_doc()},
    )
    await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gdrive", "name": "n-gd", "document": _gdrive_doc()},
    )
    resp = await client.get("/api/v1/rep-specs?provider=gdrive", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1  # exactly one gdrive row was created
    assert all(item["provider"] == "gdrive" for item in body["items"])


@pytest.mark.asyncio
async def test_list_pagination_has_more_flips_at_limit(client):
    for i in range(3):
        await client.post(
            "/api/v1/rep-specs",
            headers=HEADERS,
            json={"provider": "gcs", "name": f"p{i}", "document": _gcs_doc()},
        )
    resp = await client.get("/api/v1/rep-specs?limit=2&offset=0", headers=HEADERS)
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True

    resp2 = await client.get("/api/v1/rep-specs?limit=2&offset=2", headers=HEADERS)
    body2 = resp2.json()
    assert len(body2["items"]) == 1  # the third item is on page 2
    assert body2["has_more"] is False


@pytest.mark.asyncio
async def test_list_requires_api_key(client):
    resp = await client.get("/api/v1/rep-specs")  # no headers
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_requires_api_key(client):
    resp = await client.post(
        "/api/v1/rep-specs",
        json={"provider": "gcs", "name": "x", "document": _gcs_doc()},
    )  # no headers
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_by_id_requires_api_key(client):
    resp = await client.get("/api/v1/rep-specs/01J0000000000000000000000Z")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/rep-specs — query-param bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_limit_too_high_returns_422(client):
    resp = await client.get("/api/v1/rep-specs?limit=501", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_limit_zero_returns_422(client):
    resp = await client.get("/api/v1/rep-specs?limit=0", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_negative_offset_returns_422(client):
    resp = await client.get("/api/v1/rep-specs?offset=-1", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_empty_provider_returns_422(client):
    resp = await client.get("/api/v1/rep-specs?provider=", headers=HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/v1/rep-specs/{rep_spec_id}  (archiver#83, tiers 1+2)
#
# Contract: `name` always mutable; `document` mutable only while the RepSpec is
# a draft (zero assignment rows, active or deactivated); `provider` frozen.
# See docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md.
# ---------------------------------------------------------------------------


async def _create_spec(client, *, name: str = "draft", document: dict | None = None) -> dict:
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": name, "document": document or _gcs_doc()},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _assign_spec(session, spec_id: str, *, deactivated: bool = False) -> None:
    """Attach an assignment row directly, bypassing rep_fields validation."""
    item = InfoItem(name=f"item-{spec_id[:8]}", rep_fields={})
    session.add(item)
    await session.flush()
    session.add(
        InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=ULID.from_str(spec_id),
            activated_at=datetime.now(UTC),
            deactivated_at=datetime.now(UTC) if deactivated else None,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_patch_renames_a_draft(client):
    spec = await _create_spec(client, name="before")
    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"name": "after"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "after"


@pytest.mark.asyncio
async def test_patch_replaces_document_on_a_draft(client):
    spec = await _create_spec(client)
    new_doc = _gcs_doc() | {"path_template": "corrected/{info_item.slug}/{source_revision.id}.html"}

    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"document": new_doc},
    )
    assert resp.status_code == 200, resp.text
    assert (
        resp.json()["document"]["path_template"]
        == "corrected/{info_item.slug}/{source_revision.id}.html"
    )


@pytest.mark.asyncio
async def test_patch_stamps_updated_at(client):
    spec = await _create_spec(client)
    assert spec["updated_at"] is None

    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"name": "renamed"},
    )
    assert resp.json()["updated_at"] is not None


@pytest.mark.asyncio
async def test_patch_renames_assigned_spec(client, session):
    """Tier 1: name is editable regardless of assignment state."""
    spec = await _create_spec(client, name="before")
    await _assign_spec(session, spec["rep_spec_id"])

    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"name": "after"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "after"


@pytest.mark.asyncio
async def test_patch_document_on_assigned_spec_returns_409(client, session):
    spec = await _create_spec(client)
    await _assign_spec(session, spec["rep_spec_id"])

    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={
            "document": _gcs_doc() | {"path_template": "nope/{info_item.slug}/{source_revision.id}"}
        },
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["kind"] == "conflict"
    assert detail["data"]["assignment_count"] == 1


@pytest.mark.asyncio
async def test_patch_document_blocked_by_deactivated_assignment(client, session):
    """The draft gate counts deactivated assignments too."""
    spec = await _create_spec(client)
    await _assign_spec(session, spec["rep_spec_id"], deactivated=True)

    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={
            "document": _gcs_doc() | {"path_template": "nope/{info_item.slug}/{source_revision.id}"}
        },
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_patch_rejects_provider_change(client):
    spec = await _create_spec(client)
    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"document": _gdrive_doc()},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["kind"] == "schema"
    assert any(e["path"] == "/provider" for e in detail["errors"])


@pytest.mark.asyncio
async def test_patch_rejects_invalid_document(client):
    spec = await _create_spec(client)
    bad = _gcs_doc()
    del bad["path_template"]

    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"document": bad},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["kind"] == "schema"
    assert detail["message"] == "invalid rep_spec"


@pytest.mark.asyncio
async def test_patch_rejects_extra_fields(client):
    spec = await _create_spec(client)
    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"name": "x", "provider": "gdrive"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_returns_404_for_unknown_id(client):
    resp = await client.patch(
        "/api/v1/rep-specs/01J0000000000000000000000Z",
        headers=HEADERS,
        json={"name": "x"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["kind"] == "lookup"


@pytest.mark.asyncio
async def test_patch_returns_422_for_malformed_ulid(client):
    resp = await client.patch("/api/v1/rep-specs/not-a-ulid", headers=HEADERS, json={"name": "x"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_requires_api_key(client):
    spec = await _create_spec(client)
    resp = await client.patch(f"/api/v1/rep-specs/{spec['rep_spec_id']}", json={"name": "x"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_rejects_explicit_null_name(client):
    """`null` is not a way to clear a NOT NULL column — reject rather than no-op."""
    spec = await _create_spec(client)
    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"name": None},
    )
    assert resp.status_code == 422, resp.text
    assert "null" in resp.text.lower()


@pytest.mark.asyncio
async def test_patch_rejects_explicit_null_document(client):
    spec = await _create_spec(client)
    resp = await client.patch(
        f"/api/v1/rep-specs/{spec['rep_spec_id']}",
        headers=HEADERS,
        json={"document": None},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_empty_body_is_a_no_op(client):
    """Omission still means 'leave untouched' — distinct from explicit null."""
    spec = await _create_spec(client, name="untouched")
    resp = await client.patch(f"/api/v1/rep-specs/{spec['rep_spec_id']}", headers=HEADERS, json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "untouched"
    assert body["updated_at"] is None
