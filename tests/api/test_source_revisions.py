"""Tests for POST /api/v1/source-revisions (idempotent) and PATCH /{id}.

POST covers:
1. Happy insert → 201, fields round-trip
2. Idempotent re-POST → 200, same source_revision_id
3. Different fingerprint, same source → 201, new source_revision_id
4. Bad fingerprint format (no sha256: prefix) → 422
5. Bad fingerprint format (uppercase hex) → 422
6. Unknown info_source_id → 404
7. Missing X-API-Key → 403
8. Cache fields populate → response carries them back
9. Optional fields default to None

PATCH covers:
10. Clear both cache fields (explicit null) → 200, both NULL
11. Clear only one field → 200, other field retained
12. Update to a non-null value → 200, new value set
13. Empty body {} → 200, no changes
14. Unknown source_revision_id → 404
15. Missing X-API-Key → 403

Outbox covers:
16. New revision → outbox row exists with correct payload shape
17. Duplicate POST → no new outbox row
18. bindings reflects active (info_item_id, role) pairs
19. Deactivated bindings excluded from bindings
20. No bindings → empty list, still emits
21. Fragment role propagated in bindings
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource

HEADERS = {"X-API-Key": "test-secret-key"}

# Valid 64-char hex fingerprints
FP_VALID = "sha256:" + "a" * 64
FP_VALID_2 = "sha256:" + "b" * 64


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ARCHIVER_API_KEY", "test-secret-key")


@pytest.fixture
async def info_source(session) -> InfoSource:
    """Root InfoSource for source-revision tests."""
    src = InfoSource(
        source_spec={
            "schema_version": 1,
            "target": {"url": "https://example.com/rev-test"},
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        },
        schema_version=1,
    )
    session.add(src)
    await session.flush()
    return src


# ---------------------------------------------------------------------------
# Test 1: Happy insert → 201, fields round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_source_revision_happy_path(client, info_source):
    source_id = str(info_source.info_source_id)
    captured = "2026-05-08T12:00:00.000000Z"

    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": source_id,
            "content_fingerprint": FP_VALID,
            "captured_at": captured,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert "source_revision_id" in body
    assert body["info_source_id"] == source_id
    assert body["content_fingerprint"] == FP_VALID
    assert body["content_size_bytes"] is None
    assert body["content_media_type"] is None
    assert body["content_cache_uri"] is None
    assert body["content_cache_expires_at"] is None


# ---------------------------------------------------------------------------
# Test 2: Idempotent re-POST → 200, same source_revision_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_source_revision_idempotent(client, info_source):
    source_id = str(info_source.info_source_id)
    payload = {
        "info_source_id": source_id,
        "content_fingerprint": FP_VALID,
        "captured_at": "2026-05-08T12:00:00.000000Z",
    }

    r1 = await client.post("/api/v1/source-revisions", headers=HEADERS, json=payload)
    r2 = await client.post("/api/v1/source-revisions", headers=HEADERS, json=payload)

    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["source_revision_id"] == r2.json()["source_revision_id"]


# ---------------------------------------------------------------------------
# Test 3: Different fingerprint, same source → 201, new source_revision_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_source_revision_different_fingerprint(client, info_source):
    source_id = str(info_source.info_source_id)

    r1 = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": source_id,
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    r2 = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": source_id,
            "content_fingerprint": FP_VALID_2,
            "captured_at": "2026-05-08T13:00:00.000000Z",
        },
    )

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["source_revision_id"] != r2.json()["source_revision_id"]


# ---------------------------------------------------------------------------
# Test 4: Bad fingerprint format (no sha256: prefix) → 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_fingerprint_no_prefix_returns_422(client, info_source):
    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": "a" * 64,  # missing sha256: prefix
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 5: Bad fingerprint format (uppercase hex) → 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_fingerprint_uppercase_returns_422(client, info_source):
    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": "sha256:" + "A" * 64,  # uppercase not allowed
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 6: Unknown info_source_id → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_info_source_returns_404(client):
    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": "01HZZZZZZZZZZZZZZZZZZZZZZZ",
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "info_source not found"


# ---------------------------------------------------------------------------
# Test 6b: Malformed info_source_id ULID in body → 422 with envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_info_source_id_ulid_returns_422(client):
    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": "not-a-ulid",
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"] == "info_source_id is not a valid ULID"
    assert detail["errors"][0]["path"] == "/info_source_id"
    assert detail["errors"][0]["code"] == "invalid_ulid"


# ---------------------------------------------------------------------------
# Test 7: Missing X-API-Key → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_api_key_returns_403(client, info_source):
    response = await client.post(
        "/api/v1/source-revisions",
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test 8: Cache fields populate → response carries them back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_fields_round_trip(client, info_source):
    source_id = str(info_source.info_source_id)
    cache_uri = "file:///data/cache/rev123.html"
    expires = "2026-06-01T00:00:00.000000Z"

    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": source_id,
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
            "content_size_bytes": 4096,
            "content_media_type": "text/html",
            "content_cache_uri": cache_uri,
            "content_cache_expires_at": expires,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["content_size_bytes"] == 4096
    assert body["content_media_type"] == "text/html"
    assert body["content_cache_uri"] == cache_uri
    assert body["content_cache_expires_at"] is not None


# ---------------------------------------------------------------------------
# Test 9: Optional fields default to None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optional_fields_default_to_none(client, info_source):
    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["content_size_bytes"] is None
    assert body["content_media_type"] is None
    assert body["content_cache_uri"] is None
    assert body["content_cache_expires_at"] is None


# ---------------------------------------------------------------------------
# Helpers — create a revision with cache fields set
# ---------------------------------------------------------------------------


async def _create_rev_with_cache(client, info_source) -> dict:
    """POST a SourceRevision with both cache fields populated; return body."""
    resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
            "content_cache_uri": "file:///data/cache/rev.html",
            "content_cache_expires_at": "2026-06-01T00:00:00.000000Z",
        },
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Test 10: Clear both cache fields → 200, both NULL in response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_clear_both_cache_fields(client, info_source):
    created = await _create_rev_with_cache(client, info_source)
    rev_id = created["source_revision_id"]

    response = await client.patch(
        f"/api/v1/source-revisions/{rev_id}",
        headers=HEADERS,
        json={"content_cache_uri": None, "content_cache_expires_at": None},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_revision_id"] == rev_id
    assert body["content_cache_uri"] is None
    assert body["content_cache_expires_at"] is None


# ---------------------------------------------------------------------------
# Test 11: Clear only one field; other is retained
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_clear_one_field_retains_other(client, info_source):
    created = await _create_rev_with_cache(client, info_source)
    rev_id = created["source_revision_id"]
    original_expires = created["content_cache_expires_at"]
    assert original_expires is not None

    response = await client.patch(
        f"/api/v1/source-revisions/{rev_id}",
        headers=HEADERS,
        json={"content_cache_uri": None},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content_cache_uri"] is None
    # content_cache_expires_at must be unchanged
    assert body["content_cache_expires_at"] == original_expires


# ---------------------------------------------------------------------------
# Test 12: Update to a non-null value → 200, new value set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_update_to_new_value(client, info_source):
    created = await _create_rev_with_cache(client, info_source)
    rev_id = created["source_revision_id"]
    new_uri = "file:///data/cache/updated.html"

    response = await client.patch(
        f"/api/v1/source-revisions/{rev_id}",
        headers=HEADERS,
        json={"content_cache_uri": new_uri},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content_cache_uri"] == new_uri
    # expires_at retained
    assert body["content_cache_expires_at"] == created["content_cache_expires_at"]


# ---------------------------------------------------------------------------
# Test 13: Empty body → 200, no changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_empty_body_no_changes(client, info_source):
    created = await _create_rev_with_cache(client, info_source)
    rev_id = created["source_revision_id"]

    response = await client.patch(
        f"/api/v1/source-revisions/{rev_id}",
        headers=HEADERS,
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    # All fields unchanged
    assert body["content_cache_uri"] == created["content_cache_uri"]
    assert body["content_cache_expires_at"] == created["content_cache_expires_at"]


# ---------------------------------------------------------------------------
# Test 14: Unknown source_revision_id → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_unknown_id_returns_404(client):
    response = await client.patch(
        "/api/v1/source-revisions/01HZZZZZZZZZZZZZZZZZZZZZZZ",
        headers=HEADERS,
        json={"content_cache_uri": None},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "source_revision not found"


# ---------------------------------------------------------------------------
# Test 14b: Malformed source_revision_id path param → 422 with envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_invalid_ulid_returns_422(client):
    response = await client.patch(
        "/api/v1/source-revisions/not-a-ulid",
        headers=HEADERS,
        json={"content_cache_uri": None},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"] == "source_revision_id is not a valid ULID"
    assert detail["errors"][0]["path"] == "/source_revision_id"
    assert detail["errors"][0]["code"] == "invalid_ulid"


# ---------------------------------------------------------------------------
# Test 15: Missing X-API-Key → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_missing_api_key_returns_403(client, info_source):
    created = await _create_rev_with_cache(client, info_source)
    rev_id = created["source_revision_id"]

    response = await client.patch(
        f"/api/v1/source-revisions/{rev_id}",
        json={"content_cache_uri": None},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Helpers for outbox tests
# ---------------------------------------------------------------------------


async def _outbox_count(session) -> int:
    """Return total number of changes_outbox rows visible in this session."""
    result = await session.execute(select(func.count()).select_from(ChangesOutboxRow))
    return result.scalar_one()


async def _make_info_item(session) -> InfoItem:
    item = InfoItem(name="test-item")
    session.add(item)
    await session.flush()
    return item


async def _bind_item_to_source(
    session, item: InfoItem, source: InfoSource, *, deactivated: bool = False
) -> InfoItemSource:
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        role=None,
    )
    if deactivated:
        binding.deactivated_at = datetime.now(UTC)
    session.add(binding)
    await session.flush()
    return binding


# ---------------------------------------------------------------------------
# Test 16: New revision → outbox row exists with correct payload shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_revision_writes_outbox_row(client, session, info_source):
    source_id = str(info_source.info_source_id)

    resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": source_id,
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert resp.status_code == 201
    rev_id = resp.json()["source_revision_id"]

    count = await _outbox_count(session)
    assert count == 1

    result = await session.execute(select(ChangesOutboxRow))
    row = result.scalar_one()
    assert row.topic == "info.changes"
    payload = row.payload
    assert payload["event_type"] == "source_revision_captured"
    assert payload["info_source_id"] == source_id
    assert payload["source_revision_id"] == rev_id
    assert payload["content_fingerprint"] == FP_VALID
    assert isinstance(payload["bindings"], list)
    assert "occurred_at" in payload


# ---------------------------------------------------------------------------
# Test 17: Duplicate POST → no new outbox row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_post_does_not_write_second_outbox_row(client, session, info_source):
    payload = {
        "info_source_id": str(info_source.info_source_id),
        "content_fingerprint": FP_VALID,
        "captured_at": "2026-05-08T12:00:00.000000Z",
    }

    r1 = await client.post("/api/v1/source-revisions", headers=HEADERS, json=payload)
    assert r1.status_code == 201
    assert await _outbox_count(session) == 1

    r2 = await client.post("/api/v1/source-revisions", headers=HEADERS, json=payload)
    assert r2.status_code == 200
    # Still only one outbox row — idempotent no-op must not write a second
    assert await _outbox_count(session) == 1


# ---------------------------------------------------------------------------
# Test 18: bindings reflects active (info_item_id, role) pairs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbox_payload_includes_active_bindings(client, session, info_source):
    item1 = await _make_info_item(session)
    item2 = await _make_info_item(session)
    session.add_all(
        [
            InfoItemSource(
                info_item_id=item1.info_item_id,
                info_source_id=info_source.info_source_id,
                role=None,
            ),
            InfoItemSource(
                info_item_id=item2.info_item_id,
                info_source_id=info_source.info_source_id,
                role=None,
            ),
        ]
    )
    await session.flush()

    resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert resp.status_code == 201

    result = await session.execute(select(ChangesOutboxRow))
    row = result.scalar_one()
    bindings = row.payload["bindings"]
    ids = {b["info_item_id"] for b in bindings}
    roles = {b["role"] for b in bindings}
    assert {str(item1.info_item_id), str(item2.info_item_id)} == ids
    assert roles == {None}


# ---------------------------------------------------------------------------
# Test 19: Deactivated bindings excluded from bindings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbox_payload_excludes_deactivated_bindings(client, session, info_source):
    active_item = await _make_info_item(session)
    inactive_item = await _make_info_item(session)

    session.add(
        InfoItemSource(
            info_item_id=active_item.info_item_id,
            info_source_id=info_source.info_source_id,
            role=None,
        )
    )
    await session.flush()

    await _bind_item_to_source(session, inactive_item, info_source, deactivated=True)

    resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert resp.status_code == 201

    result = await session.execute(select(ChangesOutboxRow))
    row = result.scalar_one()
    bindings = row.payload["bindings"]
    item_ids = {b["info_item_id"] for b in bindings}
    assert str(active_item.info_item_id) in item_ids
    assert str(inactive_item.info_item_id) not in item_ids
    assert len(bindings) == 1


# ---------------------------------------------------------------------------
# Test 20: No bindings → empty bindings list, still emits outbox row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbox_payload_empty_list_when_no_bindings(client, session, info_source):
    resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert resp.status_code == 201

    count = await _outbox_count(session)
    assert count == 1

    result = await session.execute(select(ChangesOutboxRow))
    row = result.scalar_one()
    assert row.payload["bindings"] == []


# ---------------------------------------------------------------------------
# Test 21: Fragment role propagated in bindings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbox_payload_carries_fragment_role(client, session):
    """Cross-check / sub_aspect roles are included in bindings; consumers filter."""
    # Create root InfoSource
    root_source = InfoSource(
        source_spec={
            "schema_version": 1,
            "target": {"url": "https://example.com/fragment-role-root"},
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        },
        schema_version=1,
    )
    session.add(root_source)
    await session.flush()

    # Create fragment InfoSource (parent = root); no target.url → url col stays NULL
    fragment_source = InfoSource(
        parent_info_source_id=root_source.info_source_id,
        source_spec={
            "schema_version": 1,
            "extraction": {"algorithm": "css", "selector": ".sub-section"},
            "fingerprint": {},
        },
        schema_version=1,
    )
    session.add(fragment_source)
    await session.flush()

    # Create an InfoItem and bind the fragment with role='sub_aspect'
    item = InfoItem(name="fragment-role-test-item")
    session.add(item)
    await session.flush()

    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=fragment_source.info_source_id,
            role="sub_aspect",
        )
    )
    await session.flush()

    # POST a revision against the FRAGMENT source
    resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(fragment_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
        },
    )
    assert resp.status_code == 201

    result = await session.execute(select(ChangesOutboxRow))
    row = result.scalar_one()
    bindings = row.payload["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["info_item_id"] == str(item.info_item_id)
    assert bindings[0]["role"] == "sub_aspect"


# ---------------------------------------------------------------------------
# Client-supplied source_revision_id (v2.2.0)
# ---------------------------------------------------------------------------
#
# Watcher pre-allocates the SourceRevision's ULID so it can write the
# content_cache_uri scratch file as `<source_revision_id>.bin` BEFORE the POST
# round-trips. Server honors a supplied ULID when present; idempotency on
# (info_source_id, content_fingerprint) still wins on re-POST.


_CLIENT_ULID = "01JV0000000000000000000000"  # any well-formed ULID
_CLIENT_ULID_ALT = "01JV0000000000000000000001"


@pytest.mark.asyncio
async def test_client_supplied_ulid_honored_on_insert(client, info_source):
    """Server uses the client-supplied source_revision_id on a fresh insert."""
    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
            "source_revision_id": _CLIENT_ULID,
        },
    )
    assert response.status_code == 201
    assert response.json()["source_revision_id"] == _CLIENT_ULID


@pytest.mark.asyncio
async def test_client_supplied_ulid_idempotent_match(client, info_source):
    """Re-POST with the same supplied ULID and same (source, fingerprint) → 200."""
    payload = {
        "info_source_id": str(info_source.info_source_id),
        "content_fingerprint": FP_VALID,
        "captured_at": "2026-05-08T12:00:00.000000Z",
        "source_revision_id": _CLIENT_ULID,
    }
    r1 = await client.post("/api/v1/source-revisions", headers=HEADERS, json=payload)
    r2 = await client.post("/api/v1/source-revisions", headers=HEADERS, json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["source_revision_id"] == _CLIENT_ULID
    assert r2.json()["source_revision_id"] == _CLIENT_ULID


@pytest.mark.asyncio
async def test_client_supplied_ulid_idempotency_returns_existing_id(client, info_source):
    """Re-POST with a different supplied ULID still matches on (source, fingerprint).

    Idempotency wins. The server returns the EXISTING revision's id,
    ignoring the second client-supplied ULID. Watcher's responsibility to
    reconcile its scratch filename if the response carries a different id.
    """
    base = {
        "info_source_id": str(info_source.info_source_id),
        "content_fingerprint": FP_VALID,
        "captured_at": "2026-05-08T12:00:00.000000Z",
    }
    r1 = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={**base, "source_revision_id": _CLIENT_ULID},
    )
    r2 = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={**base, "source_revision_id": _CLIENT_ULID_ALT},
    )
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["source_revision_id"] == _CLIENT_ULID
    assert r2.json()["source_revision_id"] == _CLIENT_ULID  # NOT _CLIENT_ULID_ALT


@pytest.mark.asyncio
async def test_client_supplied_ulid_collision_with_different_pair_returns_409(client, info_source):
    """Supplied ULID already used by a different (source, fingerprint) → 409."""
    # First, claim the ULID for one (source, fingerprint).
    r1 = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
            "source_revision_id": _CLIENT_ULID,
        },
    )
    assert r1.status_code == 201

    # Re-use the SAME ULID with a DIFFERENT fingerprint → 409.
    r2 = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID_2,
            "captured_at": "2026-05-08T13:00:00.000000Z",
            "source_revision_id": _CLIENT_ULID,
        },
    )
    assert r2.status_code == 409
    detail = r2.json()["detail"]
    assert detail["kind"] == "conflict"
    assert detail["data"]["existing_info_source_id"] == str(info_source.info_source_id)
    assert detail["data"]["existing_content_fingerprint"] == FP_VALID


@pytest.mark.asyncio
async def test_client_supplied_ulid_invalid_format_returns_422(client, info_source):
    """Supplied source_revision_id that isn't a valid ULID → 422 with envelope."""
    response = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": str(info_source.info_source_id),
            "content_fingerprint": FP_VALID,
            "captured_at": "2026-05-08T12:00:00.000000Z",
            "source_revision_id": "not-a-ulid",
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"] == "source_revision_id is not a valid ULID"
    assert detail["errors"][0]["path"] == "/source_revision_id"
    assert detail["errors"][0]["code"] == "invalid_ulid"
