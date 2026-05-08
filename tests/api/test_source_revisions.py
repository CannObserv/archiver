"""Tests for POST /api/v1/source-revisions (idempotent).

Covers:
1. Happy insert → 201, fields round-trip
2. Idempotent re-POST → 200, same source_revision_id
3. Different fingerprint, same source → 201, new source_revision_id
4. Bad fingerprint format (no sha256: prefix) → 422
5. Bad fingerprint format (uppercase hex) → 422
6. Unknown info_source_id → 404
7. Missing X-API-Key → 403
8. Cache fields populate → response carries them back
9. Optional fields default to None
"""

import pytest

from src.core.models import InfoSource

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
