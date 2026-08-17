"""Tests for v2 validate-* and resolve-rep-fields tool endpoints."""

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}


# ---------------------------------------------------------------------------
# POST /api/v1/tools/validate-source-spec
# ---------------------------------------------------------------------------

VALID_SOURCE_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "full_page"},
    "fingerprint": {},
}


@pytest.mark.asyncio
async def test_validate_source_spec_valid_returns_200_valid_true(client):
    response = await client.post(
        "/api/v1/tools/validate-source-spec",
        headers=HEADERS,
        json={"document": VALID_SOURCE_SPEC},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"valid": True, "errors": []}


@pytest.mark.asyncio
async def test_validate_source_spec_invalid_returns_200_valid_false(client):
    bad = dict(VALID_SOURCE_SPEC)
    bad.pop("extraction")  # missing required field
    response = await client.post(
        "/api/v1/tools/validate-source-spec",
        headers=HEADERS,
        json={"document": bad},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) >= 1
    err = body["errors"][0]
    assert "path" in err
    assert "message" in err


@pytest.mark.asyncio
async def test_validate_source_spec_css_without_selector(client):
    response = await client.post(
        "/api/v1/tools/validate-source-spec",
        headers=HEADERS,
        json={
            "document": {
                **VALID_SOURCE_SPEC,
                "extraction": {"algorithm": "css"},
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False


@pytest.mark.asyncio
async def test_validate_source_spec_requires_api_key(client):
    response = await client.post(
        "/api/v1/tools/validate-source-spec",
        json={"document": VALID_SOURCE_SPEC},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/tools/validate-rep-spec
# ---------------------------------------------------------------------------

VALID_REP_SPEC = {
    "provider": "gcs",
    "credentials_alias": "default",
    "path_template": "bucket/{gcs.object_name}/{source_revision.id}",
    "required_fields": ["gcs.object_name"],
}


@pytest.mark.asyncio
async def test_validate_rep_spec_valid_returns_200_valid_true(client):
    response = await client.post(
        "/api/v1/tools/validate-rep-spec",
        headers=HEADERS,
        json={"document": VALID_REP_SPEC},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["errors"] == []


@pytest.mark.asyncio
async def test_validate_rep_spec_unknown_provider_returns_error(client):
    bad = {**VALID_REP_SPEC, "provider": "unknown_provider_xyz"}
    response = await client.post(
        "/api/v1/tools/validate-rep-spec",
        headers=HEADERS,
        json={"document": bad},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("unknown provider" in e["message"] for e in body["errors"])


@pytest.mark.asyncio
async def test_validate_rep_spec_requires_api_key(client):
    response = await client.post(
        "/api/v1/tools/validate-rep-spec",
        json={"document": VALID_REP_SPEC},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/tools/validate-rep-fields
# ---------------------------------------------------------------------------

VALID_BAG = {"gcs": {"object_name": "co-active-licenses"}}


@pytest.mark.asyncio
async def test_validate_rep_fields_valid_bag_returns_200_valid_true(client):
    response = await client.post(
        "/api/v1/tools/validate-rep-fields",
        headers=HEADERS,
        json={"bag": VALID_BAG},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["errors"] == []


@pytest.mark.asyncio
async def test_validate_rep_fields_with_required_fields_present(client):
    response = await client.post(
        "/api/v1/tools/validate-rep-fields",
        headers=HEADERS,
        json={"bag": VALID_BAG, "required_fields": ["gcs.object_name"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True


@pytest.mark.asyncio
async def test_validate_rep_fields_missing_required_field_returns_errors(client):
    response = await client.post(
        "/api/v1/tools/validate-rep-fields",
        headers=HEADERS,
        json={"bag": {}, "required_fields": ["gcs.object_name"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert len(body["errors"]) >= 1


@pytest.mark.asyncio
async def test_validate_rep_fields_requires_api_key(client):
    response = await client.post(
        "/api/v1/tools/validate-rep-fields",
        json={"bag": VALID_BAG},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/tools/resolve-rep-fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_rep_fields_adds_slug_companions(client):
    response = await client.post(
        "/api/v1/tools/resolve-rep-fields",
        headers=HEADERS,
        json={"bag": {"gcs": {"object_name": "co/active licenses"}}},
    )
    assert response.status_code == 200
    body = response.json()
    assert "bag" in body
    assert body["bag"]["gcs"]["object_name_slug"] == "co_active_licenses"


@pytest.mark.asyncio
async def test_resolve_rep_fields_acronym_or_title_derived(client):
    response = await client.post(
        "/api/v1/tools/resolve-rep-fields",
        headers=HEADERS,
        json={"bag": {"org": {"acronym": "CDPHE", "title": "Colorado Dept"}}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["bag"]["org"]["acronym_or_title"] == "CDPHE"
    assert body["bag"]["org"]["acronym_or_title_slug"] == "cdphe"


@pytest.mark.asyncio
async def test_resolve_rep_fields_idempotent_existing_slugs(client):
    """Pre-existing _slug keys are not overwritten."""
    response = await client.post(
        "/api/v1/tools/resolve-rep-fields",
        headers=HEADERS,
        json={"bag": {"gcs": {"object_name": "foo", "object_name_slug": "my-custom-slug"}}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["bag"]["gcs"]["object_name_slug"] == "my-custom-slug"


@pytest.mark.asyncio
async def test_resolve_rep_fields_requires_api_key(client):
    response = await client.post(
        "/api/v1/tools/resolve-rep-fields",
        json={"bag": {}},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/tools/validate-watch-spec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_watch_spec_valid_returns_200_valid_true(client):
    response = await client.post(
        "/api/v1/tools/validate-watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "interval": "1d"}},
    )
    assert response.status_code == 200
    assert response.json() == {"valid": True, "errors": []}


@pytest.mark.asyncio
async def test_validate_watch_spec_invalid_returns_200_valid_false(client):
    response = await client.post(
        "/api/v1/tools/validate-watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "interval": "daily"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any(e["path"] == "/interval" for e in body["errors"])


@pytest.mark.asyncio
async def test_validate_watch_spec_rejects_a_document_carrying_active(client):
    """Pause state is the sibling column, not a key in the cadence document."""
    response = await client.post(
        "/api/v1/tools/validate-watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "active": True}},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
