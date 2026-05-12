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
    assert detail["kind"] == "schema"
    assert detail["message"] == "invalid source_spec"
    assert isinstance(detail["errors"], list)
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
    assert detail["kind"] == "schema"
    assert detail["message"] == "invalid source_spec"
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
    detail = resp.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "parent InfoSource not found"


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
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"] == "parent_info_source_id must reference a root InfoSource"
    assert detail["errors"][0]["path"] == "/parent_info_source_id"
    assert detail["errors"][0]["code"] == "parent_must_be_root"


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
    assert detail["kind"] == "conflict"
    assert detail["message"] == "an InfoSource already exists for this URL"
    assert detail["data"]["existing_info_source_id"] == first_id
    assert detail["data"]["url"] == "https://example.com/p"


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
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"] == "parent_info_source_id is not a valid ULID"
    assert detail["errors"][0]["path"] == "/parent_info_source_id"
    assert detail["errors"][0]["code"] == "invalid_ulid"


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
    detail = resp.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "InfoSource not found"


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
    body = resp.json()
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert body["has_more"] is False
    ids = {row["info_source_id"] for row in body["items"]}
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
    body = resp.json()
    ids = {row["info_source_id"] for row in body["items"]}
    assert ids == {frag1.json()["info_source_id"], frag2.json()["info_source_id"]}
    # neither root must appear in fragment-filtered results
    assert root_a_id not in ids
    assert root_b.json()["info_source_id"] not in ids


@pytest.mark.asyncio
async def test_list_pagination_pages_correctly(client):
    ids = []
    for path in ("a", "b", "c", "d", "e"):
        resp = await client.post(
            "/api/v1/info-sources",
            headers=HEADERS,
            json={"source_spec": _root_doc(f"https://example.com/{path}")},
        )
        ids.append(resp.json()["info_source_id"])

    p1 = (await client.get("/api/v1/info-sources?limit=2&offset=0", headers=HEADERS)).json()
    p2 = (await client.get("/api/v1/info-sources?limit=2&offset=2", headers=HEADERS)).json()
    p3 = (await client.get("/api/v1/info-sources?limit=2&offset=4", headers=HEADERS)).json()

    assert [r["info_source_id"] for r in p1["items"]] == ids[0:2]
    assert p1["has_more"] is True
    assert p1["limit"] == 2
    assert p1["offset"] == 0
    assert [r["info_source_id"] for r in p2["items"]] == ids[2:4]
    assert p2["has_more"] is True
    assert [r["info_source_id"] for r in p3["items"]] == ids[4:5]
    assert p3["has_more"] is False


@pytest.mark.asyncio
async def test_list_pagination_composes_with_parent_filter(client):
    root = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"source_spec": _root_doc("https://example.com/root-p")},
    )
    root_id = root.json()["info_source_id"]

    frag_ids = []
    for _ in range(3):
        resp = await client.post(
            "/api/v1/info-sources",
            headers=HEADERS,
            json={"source_spec": _fragment_doc(), "parent_info_source_id": root_id},
        )
        frag_ids.append(resp.json()["info_source_id"])

    p1 = (
        await client.get(
            f"/api/v1/info-sources?parent_info_source_id={root_id}&limit=2&offset=0",
            headers=HEADERS,
        )
    ).json()
    p2 = (
        await client.get(
            f"/api/v1/info-sources?parent_info_source_id={root_id}&limit=2&offset=2",
            headers=HEADERS,
        )
    ).json()

    assert [r["info_source_id"] for r in p1["items"]] == frag_ids[0:2]
    assert p1["has_more"] is True
    assert [r["info_source_id"] for r in p2["items"]] == frag_ids[2:3]
    assert p2["has_more"] is False


@pytest.mark.asyncio
async def test_list_limit_too_high_returns_422(client):
    resp = await client.get("/api/v1/info-sources?limit=501", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_limit_zero_returns_422(client):
    resp = await client.get("/api/v1/info-sources?limit=0", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_negative_offset_returns_422(client):
    resp = await client.get("/api/v1/info-sources?offset=-1", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_filter_by_invalid_parent_id_returns_422(client):
    resp = await client.get(
        "/api/v1/info-sources?parent_info_source_id=not-a-ulid",
        headers=HEADERS,
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"] == "parent_info_source_id is not a valid ULID"
    assert detail["errors"][0]["path"] == "/parent_info_source_id"
    assert detail["errors"][0]["code"] == "invalid_ulid"


@pytest.mark.asyncio
async def test_list_requires_api_key(client):
    resp = await client.get("/api/v1/info-sources")
    assert resp.status_code == 403
