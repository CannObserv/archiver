"""Tests for top-level /info-sources endpoints.

Covers:
- POST /info-sources (root + fragment + validation + parent + duplicate)
- GET /info-sources (filter by parent_info_source_id)
- GET /info-sources/{id}
"""

from __future__ import annotations

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ARCHIVER_API_KEY", "test-secret-key")


def _root_doc(url: str = "https://example.com/p") -> dict:
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


def _fragment_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }


# ---------------------------------------------------------------------------
# POST /api/v1/info-sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_root_returns_201_with_canonical_url(client):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc("https://EXAMPLE.com/p#frag")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"] == "https://example.com/p"
    assert body["parent_info_source_id"] is None
    assert body["schema_version"] == 1
    assert len(body["info_source_id"]) == 26


@pytest.mark.asyncio
async def test_post_fragment_returns_201_with_parent(client):
    parent_resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc()},
    )
    parent_id = parent_resp.json()["info_source_id"]

    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={
            "source_spec": _fragment_doc(),
            "parent_info_source_id": parent_id,
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["parent_info_source_id"] == parent_id
    assert body["url"] is None


@pytest.mark.asyncio
async def test_post_root_without_url_returns_422(client):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _fragment_doc()},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["message"] == "invalid source_spec"
    assert any(e["path"] == "/target/url" for e in detail["errors"])


@pytest.mark.asyncio
async def test_post_fragment_with_target_url_returns_422(client):
    parent_resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc()},
    )
    parent_id = parent_resp.json()["info_source_id"]

    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={
            "source_spec": _root_doc("https://example.com/q"),
            "parent_info_source_id": parent_id,
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(e["path"] == "/target/url" for e in detail["errors"])


@pytest.mark.asyncio
async def test_post_fragment_with_unknown_parent_returns_404(client):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={
            "source_spec": _fragment_doc(),
            "parent_info_source_id": "01HZZ00000000000000000000Z",
        },
    )
    assert resp.status_code == 404
    assert "parent" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_fragment_with_fragment_parent_returns_422(client):
    """Fragment-of-fragment chains are forbidden."""
    root_resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc()},
    )
    root_id = root_resp.json()["info_source_id"]

    frag_resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _fragment_doc(), "parent_info_source_id": root_id},
    )
    frag_id = frag_resp.json()["info_source_id"]

    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _fragment_doc(), "parent_info_source_id": frag_id},
    )
    assert resp.status_code == 422
    assert "root" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_duplicate_url_returns_409_with_existing_id(client):
    first = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc()},
    )
    first_id = first.json()["info_source_id"]

    second = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc()},
    )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["existing_info_source_id"] == first_id
    assert detail["url"] == "https://example.com/p"


@pytest.mark.asyncio
async def test_post_invalid_parent_id_returns_422(client):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={
            "source_spec": _fragment_doc(),
            "parent_info_source_id": "not-a-ulid",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_requires_api_key(client):
    resp = await client.post(
        "/api/v1/info-sources",
        json={"source_spec": _root_doc()},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_rejects_extra_fields(client):
    """schema_version must come from source_spec, not the top-level request body."""
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc(), "schema_version": 1},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/info-sources/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_id_returns_root(client):
    create_resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc()},
    )
    src_id = create_resp.json()["info_source_id"]

    resp = await client.get(f"/api/v1/info-sources/{src_id}", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["info_source_id"] == src_id
    assert body["url"] == "https://example.com/p"


@pytest.mark.asyncio
async def test_get_by_id_unknown_returns_404(client):
    resp = await client.get(
        "/api/v1/info-sources/01HZZ00000000000000000000Z",
        headers=HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_by_id_invalid_ulid_returns_422(client):
    resp = await client.get("/api/v1/info-sources/not-a-ulid", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_by_id_requires_api_key(client):
    resp = await client.get("/api/v1/info-sources/01HZZ00000000000000000000Z")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/info-sources (list / filter)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_all_when_no_filter(client):
    a = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc("https://example.com/a")},
    )
    b = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc("https://example.com/b")},
    )

    resp = await client.get("/api/v1/info-sources", headers=HEADERS)
    assert resp.status_code == 200
    ids = {row["info_source_id"] for row in resp.json()}
    assert a.json()["info_source_id"] in ids
    assert b.json()["info_source_id"] in ids


@pytest.mark.asyncio
async def test_list_filter_by_parent_returns_only_fragments(client):
    root_a = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc("https://example.com/a")},
    )
    root_a_id = root_a.json()["info_source_id"]

    root_b = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc("https://example.com/b")},
    )

    frag1 = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _fragment_doc(), "parent_info_source_id": root_a_id},
    )
    frag2 = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _fragment_doc(), "parent_info_source_id": root_a_id},
    )

    resp = await client.get(
        f"/api/v1/info-sources?parent_info_source_id={root_a_id}",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    ids = {row["info_source_id"] for row in resp.json()}
    assert ids == {frag1.json()["info_source_id"], frag2.json()["info_source_id"]}
    # neither root must appear in fragment-filtered results
    assert root_a_id not in ids
    assert root_b.json()["info_source_id"] not in ids


@pytest.mark.asyncio
async def test_list_filter_by_invalid_parent_id_returns_422(client):
    resp = await client.get(
        "/api/v1/info-sources?parent_info_source_id=not-a-ulid",
        headers=HEADERS,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_requires_api_key(client):
    resp = await client.get("/api/v1/info-sources")
    assert resp.status_code == 403
