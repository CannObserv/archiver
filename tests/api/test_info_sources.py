"""Tests for top-level /info-sources endpoints.

Covers:
- POST /info-sources (create with url + source_specs)
- PATCH /info-sources/{id}/source-specs (update specs)
- GET /info-sources (list, ?url= filter)
- GET /info-sources/{id} (detail)
"""

from __future__ import annotations

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}


def _spec(algorithm: str = "full_page", selector: str | None = None) -> dict:
    doc: dict = {
        "schema_version": 1,
        "extraction": {"algorithm": algorithm},
        "fingerprint": {},
    }
    if selector is not None:
        doc["extraction"]["selector"] = selector
    elif algorithm != "full_page":
        doc["extraction"]["selector"] = "#x"
    return doc


# ---------------------------------------------------------------------------
# POST /api/v1/info-sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_returns_201_with_canonical_url(client):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://EXAMPLE.com/p#frag", "source_specs": [_spec()]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"] == "https://example.com/p"
    assert body["source_specs"] == [_spec()]
    assert len(body["info_source_id"]) == 26


@pytest.mark.asyncio
async def test_post_multiple_specs(client):
    specs = [_spec("full_page"), _spec("css")]
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://example.com/multi", "source_specs": specs},
    )
    assert resp.status_code == 201
    assert resp.json()["source_specs"] == specs


@pytest.mark.asyncio
async def test_post_same_url_twice_creates_two_rows(client):
    payload = {"url": "https://example.com/dup", "source_specs": [_spec()]}
    r1 = await client.post("/api/v1/info-sources", headers=HEADERS, json=payload)
    r2 = await client.post("/api/v1/info-sources", headers=HEADERS, json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["info_source_id"] != r2.json()["info_source_id"]


@pytest.mark.asyncio
async def test_post_invalid_url_returns_422(client):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "not-a-url", "source_specs": [_spec()]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["kind"] == "domain"


@pytest.mark.asyncio
async def test_post_empty_specs_returns_422(client):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://example.com/p", "source_specs": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_invalid_spec_element_returns_422(client):
    bad_spec = {"schema_version": 1, "extraction": {"algorithm": "css"}, "fingerprint": {}}
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://example.com/p", "source_specs": [bad_spec]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["kind"] == "schema"


@pytest.mark.asyncio
async def test_post_mixed_families_returns_422(client):
    specs = [_spec("full_page"), _spec("jsonpath")]
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://example.com/p", "source_specs": specs},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_requires_api_key(client):
    resp = await client.post(
        "/api/v1/info-sources",
        json={"url": "https://example.com/p", "source_specs": [_spec()]},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /api/v1/info-sources/{id}/source-specs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_source_specs_updates_specs(client):
    create_resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://example.com/patch-test", "source_specs": [_spec()]},
    )
    src_id = create_resp.json()["info_source_id"]

    new_specs = [_spec("full_page"), _spec("css")]
    patch_resp = await client.patch(
        f"/api/v1/info-sources/{src_id}/source-specs",
        headers=HEADERS,
        json={"source_specs": new_specs},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["source_specs"] == new_specs
    assert patch_resp.json()["url"] == "https://example.com/patch-test"


@pytest.mark.asyncio
async def test_patch_source_specs_not_found_returns_404(client):
    resp = await client.patch(
        "/api/v1/info-sources/01JZZZZZZZZZZZZZZZZZZZZZZZ/source-specs",
        headers=HEADERS,
        json={"source_specs": [_spec()]},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/info-sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_list_returns_200(client):
    resp = await client.get("/api/v1/info-sources", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "has_more" in body


@pytest.mark.asyncio
async def test_get_list_url_filter(client):
    url_a = "https://example.com/list-filter-a"
    url_b = "https://example.com/list-filter-b"
    await client.post(
        "/api/v1/info-sources", headers=HEADERS, json={"url": url_a, "source_specs": [_spec()]}
    )
    await client.post(
        "/api/v1/info-sources", headers=HEADERS, json={"url": url_b, "source_specs": [_spec()]}
    )

    resp = await client.get(f"/api/v1/info-sources?url={url_a}", headers=HEADERS)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["url"] == url_a for i in items)


@pytest.mark.asyncio
async def test_get_list_requires_api_key(client):
    resp = await client.get("/api/v1/info-sources")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_list_pagination(client):
    url_base = "https://example.com/paginate-src-"
    for i in range(3):
        await client.post(
            "/api/v1/info-sources",
            headers=HEADERS,
            json={"url": f"{url_base}{i}", "source_specs": [_spec()]},
        )

    resp = await client.get("/api/v1/info-sources?limit=2&offset=0", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) <= 2
    assert "has_more" in body


# ---------------------------------------------------------------------------
# GET /api/v1/info-sources/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_id_returns_source(client):
    create = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://example.com/get-by-id", "source_specs": [_spec()]},
    )
    src_id = create.json()["info_source_id"]

    resp = await client.get(f"/api/v1/info-sources/{src_id}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["info_source_id"] == src_id
    assert resp.json()["url"] == "https://example.com/get-by-id"


@pytest.mark.asyncio
async def test_get_by_id_not_found(client):
    resp = await client.get("/api/v1/info-sources/01JZZZZZZZZZZZZZZZZZZZZZZZ", headers=HEADERS)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_by_id_requires_api_key(client):
    resp = await client.get("/api/v1/info-sources/01JZZZZZZZZZZZZZZZZZZZZZZZ")
    assert resp.status_code == 403
