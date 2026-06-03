"""Tests for v2 assignment + binding sub-resource endpoints.

Covers:
- POST /info-items/{id}/info-sources
- POST /info-items/{id}/rep-spec-assignments
- POST /info-items/{id}/source-revisions
- DELETE /info-items/{id}/rep-spec-assignments/{assignment_id}
- PATCH /info-items/{id}/rep-spec-assignments/{assignment_id}
"""

from datetime import UTC, datetime

import pytest

from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoSource,
    RepSpec,
    SourceRevision,
)

HEADERS = {"X-API-Key": "test-secret-key"}


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def info_item(session) -> InfoItem:
    """Minimal InfoItem for use in sub-resource tests."""
    item = InfoItem(
        name="test-item",
        description=None,
        owner=None,
        rep_fields={"gcs": {"object_name": "co/test"}},
    )
    session.add(item)
    await session.flush()
    return item


@pytest.fixture
async def info_source(session) -> InfoSource:
    """An InfoSource for binding tests."""
    src = InfoSource(
        url="https://example.com/test",
        source_specs=[
            {
                "schema_version": 1,
                "extraction": {"algorithm": "full_page"},
                "fingerprint": {},
            }
        ],
    )
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def rep_spec(session) -> RepSpec:
    """A RepSpec for assignment tests."""
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


@pytest.fixture
async def source_revision(session, info_source) -> SourceRevision:
    """A SourceRevision for bind_revision tests."""
    rev = SourceRevision(
        info_source_id=info_source.info_source_id,
        content_fingerprint="sha256:abc123",
        captured_at=datetime.now(UTC),
    )
    session.add(rev)
    await session.flush()
    return rev


# ---------------------------------------------------------------------------
# POST /info-items/{id}/info-sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_info_source_happy_path(client, info_item, info_source):
    item_id = str(info_item.info_item_id)
    source_id = str(info_source.info_source_id)

    response = await client.post(
        f"/api/v1/info-items/{item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": source_id},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["info_source_id"] == source_id
    assert "created_at" in body


@pytest.mark.asyncio
async def test_add_info_source_missing_item_returns_404(client, info_source):
    fake_item_id = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
    source_id = str(info_source.info_source_id)

    response = await client.post(
        f"/api/v1/info-items/{fake_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": source_id},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "InfoItem not found"


@pytest.mark.asyncio
async def test_add_info_source_missing_source_returns_404(client, info_item):
    item_id = str(info_item.info_item_id)
    fake_source_id = "01HZZZZZZZZZZZZZZZZZZZZZZZ"

    response = await client.post(
        f"/api/v1/info-items/{item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": fake_source_id, "role": None},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "InfoSource not found"


@pytest.mark.asyncio
async def test_add_info_source_requires_api_key(client, info_item, info_source):
    item_id = str(info_item.info_item_id)
    source_id = str(info_source.info_source_id)

    response = await client.post(
        f"/api/v1/info-items/{item_id}/info-sources",
        json={"info_source_id": source_id},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /info-items/{id}/rep-spec-assignments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_rep_spec_assignment_happy_path(client, info_item, rep_spec):
    item_id = str(info_item.info_item_id)
    spec_id = str(rep_spec.rep_spec_id)

    response = await client.post(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments",
        headers=HEADERS,
        json={"rep_spec_id": spec_id},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["rep_spec_id"] == spec_id
    assert body["deactivated_at"] is None
    assert body["public_url"] is None
    assert "activated_at" in body
    assert "id" in body


@pytest.mark.asyncio
async def test_add_rep_spec_assignment_with_explicit_activated_at(client, info_item, rep_spec):
    item_id = str(info_item.info_item_id)
    spec_id = str(rep_spec.rep_spec_id)
    activated_at = "2026-01-01T00:00:00.000000Z"

    response = await client.post(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments",
        headers=HEADERS,
        json={"rep_spec_id": spec_id, "activated_at": activated_at},
    )
    assert response.status_code == 201
    body = response.json()
    stored = datetime.fromisoformat(body["activated_at"].replace("Z", "+00:00"))
    assert stored == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_add_rep_spec_assignment_missing_item_returns_404(client, rep_spec):
    fake_id = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
    spec_id = str(rep_spec.rep_spec_id)

    response = await client.post(
        f"/api/v1/info-items/{fake_id}/rep-spec-assignments",
        headers=HEADERS,
        json={"rep_spec_id": spec_id},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "InfoItem not found"


@pytest.mark.asyncio
async def test_add_rep_spec_assignment_missing_spec_returns_404(client, info_item):
    item_id = str(info_item.info_item_id)
    fake_spec = "01HZZZZZZZZZZZZZZZZZZZZZZZ"

    response = await client.post(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments",
        headers=HEADERS,
        json={"rep_spec_id": fake_spec},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "RepSpec not found"


@pytest.mark.asyncio
async def test_add_rep_spec_assignment_incomplete_rep_fields_returns_422(client, session, rep_spec):
    """InfoItem with empty rep_fields fails required_fields check → 422."""
    # Create item with empty rep_fields (doesn't satisfy gcs.object_name required)
    item = InfoItem(name="empty-fields-item", rep_fields={})
    session.add(item)
    await session.flush()
    item_id = str(item.info_item_id)
    spec_id = str(rep_spec.rep_spec_id)

    response = await client.post(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments",
        headers=HEADERS,
        json={"rep_spec_id": spec_id},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"] == "rep_fields incomplete"
    assert any(e["path"] == "/gcs/object_name" for e in detail["errors"])
    assert all(e["code"] == "rep_fields_incomplete" for e in detail["errors"])


@pytest.mark.asyncio
async def test_add_rep_spec_assignment_requires_api_key(client, info_item, rep_spec):
    item_id = str(info_item.info_item_id)
    spec_id = str(rep_spec.rep_spec_id)

    response = await client.post(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments",
        json={"rep_spec_id": spec_id},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /info-items/{id}/source-revisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_source_revision_happy_path(client, info_item, source_revision):
    item_id = str(info_item.info_item_id)
    rev_id = str(source_revision.source_revision_id)

    response = await client.post(
        f"/api/v1/info-items/{item_id}/source-revisions",
        headers=HEADERS,
        json={"source_revision_id": rev_id},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["info_item_id"] == item_id
    assert body["source_revision_id"] == rev_id
    assert "bound_at" in body


@pytest.mark.asyncio
async def test_bind_source_revision_idempotent(client, info_item, source_revision):
    """Calling twice returns the existing binding (still 201 on second call)."""
    item_id = str(info_item.info_item_id)
    rev_id = str(source_revision.source_revision_id)
    payload = {"source_revision_id": rev_id}

    r1 = await client.post(
        f"/api/v1/info-items/{item_id}/source-revisions",
        headers=HEADERS,
        json=payload,
    )
    r2 = await client.post(
        f"/api/v1/info-items/{item_id}/source-revisions",
        headers=HEADERS,
        json=payload,
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    # bound_at should be the same (row returned unchanged)
    assert r1.json()["bound_at"] == r2.json()["bound_at"]


@pytest.mark.asyncio
async def test_bind_source_revision_missing_item_returns_404(client, source_revision):
    fake_id = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
    rev_id = str(source_revision.source_revision_id)

    response = await client.post(
        f"/api/v1/info-items/{fake_id}/source-revisions",
        headers=HEADERS,
        json={"source_revision_id": rev_id},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "InfoItem not found"


@pytest.mark.asyncio
async def test_bind_source_revision_missing_revision_returns_404(client, info_item):
    item_id = str(info_item.info_item_id)
    fake_rev = "01HZZZZZZZZZZZZZZZZZZZZZZZ"

    response = await client.post(
        f"/api/v1/info-items/{item_id}/source-revisions",
        headers=HEADERS,
        json={"source_revision_id": fake_rev},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "SourceRevision not found"


@pytest.mark.asyncio
async def test_bind_source_revision_requires_api_key(client, info_item, source_revision):
    item_id = str(info_item.info_item_id)
    rev_id = str(source_revision.source_revision_id)

    response = await client.post(
        f"/api/v1/info-items/{item_id}/source-revisions",
        json={"source_revision_id": rev_id},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /info-items/{id}/rep-spec-assignments/{assignment_id}
# ---------------------------------------------------------------------------


@pytest.fixture
async def rep_spec_assignment(session, info_item, rep_spec) -> InfoItemRepSpec:
    """An active assignment for deactivation tests."""
    airs = InfoItemRepSpec(
        info_item_id=info_item.info_item_id,
        rep_spec_id=rep_spec.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(airs)
    await session.flush()
    return airs


@pytest.mark.asyncio
async def test_deactivate_rep_spec_assignment_happy_path(client, info_item, rep_spec_assignment):
    item_id = str(info_item.info_item_id)
    assignment_id = str(rep_spec_assignment.id)

    response = await client.delete(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{assignment_id}",
        headers=HEADERS,
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_deactivate_rep_spec_assignment_missing_returns_404(client, info_item):
    item_id = str(info_item.info_item_id)
    fake_id = "01HZZZZZZZZZZZZZZZZZZZZZZZ"

    response = await client.delete(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{fake_id}",
        headers=HEADERS,
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "Assignment not found"


@pytest.mark.asyncio
async def test_deactivate_rep_spec_assignment_wrong_item_returns_404(
    client, session, rep_spec, rep_spec_assignment
):
    """Assignment exists but belongs to a different info_item_id → 404."""
    # Create a second InfoItem
    other_item = InfoItem(name="other-item", rep_fields={})
    session.add(other_item)
    await session.flush()
    other_item_id = str(other_item.info_item_id)
    assignment_id = str(rep_spec_assignment.id)

    response = await client.delete(
        f"/api/v1/info-items/{other_item_id}/rep-spec-assignments/{assignment_id}",
        headers=HEADERS,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_rep_spec_assignment_requires_api_key(
    client, info_item, rep_spec_assignment
):
    item_id = str(info_item.info_item_id)
    assignment_id = str(rep_spec_assignment.id)

    response = await client.delete(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{assignment_id}",
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /info-items/{id}/rep-spec-assignments/{assignment_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_rep_spec_assignment_public_url_active(client, info_item, rep_spec_assignment):
    """Set public_url on an active assignment row."""
    item_id = str(info_item.info_item_id)
    assignment_id = str(rep_spec_assignment.id)
    url = "https://storage.googleapis.com/bucket/co/test.json"

    response = await client.patch(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{assignment_id}",
        headers=HEADERS,
        json={"public_url": url},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == assignment_id
    assert body["public_url"] == url
    assert body["deactivated_at"] is None


@pytest.mark.asyncio
async def test_patch_rep_spec_assignment_public_url_deactivated(
    client, info_item, rep_spec_assignment
):
    """Set public_url on a deactivated row — history preservation."""
    item_id = str(info_item.info_item_id)
    assignment_id = str(rep_spec_assignment.id)

    # Deactivate first
    del_resp = await client.delete(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{assignment_id}",
        headers=HEADERS,
    )
    assert del_resp.status_code == 204

    # PATCH the now-deactivated row
    url = "https://storage.googleapis.com/bucket/co/test-archived.json"
    response = await client.patch(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{assignment_id}",
        headers=HEADERS,
        json={"public_url": url},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["public_url"] == url
    assert body["deactivated_at"] is not None  # still deactivated


@pytest.mark.asyncio
async def test_patch_rep_spec_assignment_unknown_id_returns_404(client, info_item):
    """Unknown assignment_id → 404."""
    item_id = str(info_item.info_item_id)
    fake_id = "01HZZZZZZZZZZZZZZZZZZZZZZZ"

    response = await client.patch(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{fake_id}",
        headers=HEADERS,
        json={"public_url": "https://storage.googleapis.com/bucket/x.json"},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "rep_spec_assignment not found for this info_item"


@pytest.mark.asyncio
async def test_patch_rep_spec_assignment_wrong_item_returns_404(
    client, session, rep_spec_assignment
):
    """Assignment exists but belongs to a different info_item_id → 404."""
    other_item = InfoItem(name="other-item", rep_fields={})
    session.add(other_item)
    await session.flush()
    other_item_id = str(other_item.info_item_id)
    assignment_id = str(rep_spec_assignment.id)

    response = await client.patch(
        f"/api/v1/info-items/{other_item_id}/rep-spec-assignments/{assignment_id}",
        headers=HEADERS,
        json={"public_url": "https://storage.googleapis.com/bucket/x.json"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_rep_spec_assignment_requires_api_key(client, info_item, rep_spec_assignment):
    """Missing X-API-Key → 403."""
    item_id = str(info_item.info_item_id)
    assignment_id = str(rep_spec_assignment.id)

    response = await client.patch(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{assignment_id}",
        json={"public_url": "https://storage.googleapis.com/bucket/x.json"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_patch_rep_spec_assignment_missing_public_url_returns_422(
    client, info_item, rep_spec_assignment
):
    """Empty body / missing public_url → 422 (Pydantic validation)."""
    item_id = str(info_item.info_item_id)
    assignment_id = str(rep_spec_assignment.id)

    response = await client.patch(
        f"/api/v1/info-items/{item_id}/rep-spec-assignments/{assignment_id}",
        headers=HEADERS,
        json={},
    )
    assert response.status_code == 422
