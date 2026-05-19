"""InfoItem CRUD route tests."""

from datetime import UTC, datetime

import pytest

from src.core.models import InfoItemRepSpec, InfoItemSource, RepSpec

HEADERS = {"X-API-Key": "test-secret-key"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _root_spec(url: str = "https://example.com") -> dict:
    return {
        "source_spec": {
            "schema_version": 1,
            "target": {"url": url},
            "extraction": {"algorithm": "css", "selector": "body"},
            "fingerprint": {},
        }
    }


async def _make_item(client, name: str = "Item") -> str:
    return (await client.post("/api/v1/info-items", headers=HEADERS, json={"name": name})).json()[
        "info_item_id"
    ]


async def _make_source(client, url: str = "https://example.com") -> str:
    return (
        await client.post("/api/v1/info-sources", headers=HEADERS, json=_root_spec(url))
    ).json()["info_source_id"]


async def _bind(client, item_id: str, source_id: str) -> None:
    resp = await client.post(
        f"/api/v1/info-items/{item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": source_id},
    )
    assert resp.status_code == 201


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ARCHIVER_API_KEY", "test-secret-key")


@pytest.mark.asyncio
async def test_create_info_item(client):
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={"name": "Colorado active licenses", "owner": "greg"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Colorado active licenses"
    assert body["owner"] == "greg"
    assert body["description"] is None
    assert len(body["info_item_id"]) == 26  # ULID length
    # v2 shape: empty lists when no source/rep-spec supplied
    assert body["info_item_sources"] == []
    assert body["info_item_rep_specs"] == []
    assert body["rep_fields"] == {}


@pytest.mark.asyncio
async def test_get_info_item(client):
    create = await client.post("/api/v1/info-items", headers=HEADERS, json={"name": "X"})
    item_id = create.json()["info_item_id"]
    get = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert get.status_code == 200
    assert get.json()["info_item_id"] == item_id


@pytest.mark.asyncio
async def test_get_info_item_returns_active_bindings(client):
    """GET /info-items/{id} must populate info_item_sources with active bindings."""
    item_id = (
        await client.post("/api/v1/info-items", headers=HEADERS, json={"name": "Bound"})
    ).json()["info_item_id"]
    source_id = (
        await client.post(
            "/api/v1/info-sources",
            headers=HEADERS,
            json={
                "source_spec": {
                    "target": {"url": "https://example.com"},
                    "extraction": {"algorithm": "css", "selector": "body"},
                    "fingerprint": {},
                    "schema_version": 1,
                }
            },
        )
    ).json()["info_source_id"]
    bind = await client.post(
        f"/api/v1/info-items/{item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": source_id},
    )
    assert bind.status_code == 201
    body = (await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)).json()
    assert len(body["info_item_sources"]) == 1
    assert body["info_item_sources"][0]["info_source_id"] == source_id
    assert body["info_item_sources"][0]["role"] is None  # primary


@pytest.mark.asyncio
async def test_get_info_item_404(client):
    response = await client.get("/api/v1/info-items/01HZZZZZZZZZZZZZZZZZZZZZZZ", headers=HEADERS)
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["kind"] == "lookup"
    assert detail["message"] == "InfoItem not found"


@pytest.mark.asyncio
async def test_list_info_items_empty(client):
    response = await client.get("/api/v1/info-items", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "has_more": False, "limit": 100, "offset": 0}


@pytest.mark.asyncio
async def test_list_info_items_envelope_with_rows(client):
    for n in ("a", "b", "c"):
        await client.post("/api/v1/info-items", headers=HEADERS, json={"name": n})

    response = await client.get("/api/v1/info-items", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert body["has_more"] is False
    assert len(body["items"]) == 3
    assert [it["name"] for it in body["items"]] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_list_info_items_pagination_pages_correctly(client):
    for n in ("a", "b", "c", "d", "e"):
        await client.post("/api/v1/info-items", headers=HEADERS, json={"name": n})

    p1 = (await client.get("/api/v1/info-items?limit=2&offset=0", headers=HEADERS)).json()
    p2 = (await client.get("/api/v1/info-items?limit=2&offset=2", headers=HEADERS)).json()
    p3 = (await client.get("/api/v1/info-items?limit=2&offset=4", headers=HEADERS)).json()

    assert [it["name"] for it in p1["items"]] == ["a", "b"]
    assert p1["has_more"] is True
    assert [it["name"] for it in p2["items"]] == ["c", "d"]
    assert p2["has_more"] is True
    assert [it["name"] for it in p3["items"]] == ["e"]
    assert p3["has_more"] is False


@pytest.mark.asyncio
async def test_list_info_items_limit_too_high_returns_422(client):
    resp = await client.get("/api/v1/info-items?limit=501", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_info_items_limit_zero_returns_422(client):
    resp = await client.get("/api/v1/info-items?limit=0", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_info_items_negative_offset_returns_422(client):
    resp = await client.get("/api/v1/info-items?offset=-1", headers=HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Deactivated binding exclusion (finding #5) + rep_specs population (finding #2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_info_item_excludes_deactivated_source_binding(client, session):
    """A deactivated info_item_sources row must not appear in GET /info-items/{id}."""
    item_id = await _make_item(client)
    source_id = await _make_source(client)
    await _bind(client, item_id, source_id)

    # Deactivate the binding directly in the DB.
    from ulid import ULID

    binding = await session.get(
        InfoItemSource,
        (ULID.from_str(item_id), ULID.from_str(source_id)),
    )
    binding.deactivated_at = datetime.now(UTC)
    await session.flush()

    body = (await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)).json()
    assert body["info_item_sources"] == []


@pytest.mark.asyncio
async def test_get_info_item_returns_active_rep_spec_assignments(client, session):
    """GET /info-items/{id} must populate info_item_rep_specs for active assignments."""
    from ulid import ULID

    item_id = await _make_item(client)

    rep_spec = RepSpec(
        provider="gcs",
        name="test-rep",
        schema_version=1,
        document={
            "schema_version": 1,
            "provider": "gcs",
            "credentials_alias": "default",
            "path_template": "gs://bucket/{info_item_id}",
            "required_fields": [],
        },
    )
    session.add(rep_spec)
    await session.flush()

    assignment = InfoItemRepSpec(
        info_item_id=ULID.from_str(item_id),
        rep_spec_id=rep_spec.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.flush()

    body = (await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)).json()
    assert len(body["info_item_rep_specs"]) == 1
    assert body["info_item_rep_specs"][0]["rep_spec_id"] == str(rep_spec.rep_spec_id)
    assert body["info_item_rep_specs"][0]["deactivated_at"] is None


@pytest.mark.asyncio
async def test_get_info_item_excludes_deactivated_rep_spec_assignment(client, session):
    """A deactivated info_item_rep_specs row must not appear in GET /info-items/{id}."""
    from ulid import ULID

    item_id = await _make_item(client)

    rep_spec = RepSpec(
        provider="gcs",
        name="test-rep-deact",
        schema_version=1,
        document={
            "schema_version": 1,
            "provider": "gcs",
            "credentials_alias": "default",
            "path_template": "gs://bucket/{info_item_id}",
            "required_fields": [],
        },
    )
    session.add(rep_spec)
    await session.flush()

    assignment = InfoItemRepSpec(
        info_item_id=ULID.from_str(item_id),
        rep_spec_id=rep_spec.rep_spec_id,
        activated_at=datetime.now(UTC),
        deactivated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.flush()

    body = (await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)).json()
    assert body["info_item_rep_specs"] == []


@pytest.mark.asyncio
async def test_list_info_items_populates_sources(client, session):
    """GET /info-items must populate info_item_sources for all returned items."""
    item_id = await _make_item(client, "Listed")
    source_id = await _make_source(client)
    await _bind(client, item_id, source_id)

    body = (await client.get("/api/v1/info-items", headers=HEADERS)).json()
    item_out = next(i for i in body["items"] if i["info_item_id"] == item_id)
    assert len(item_out["info_item_sources"]) == 1
    assert item_out["info_item_sources"][0]["info_source_id"] == source_id


@pytest.mark.asyncio
async def test_list_info_items_excludes_deactivated_source_binding(client, session):
    """GET /info-items must exclude deactivated info_item_sources rows."""
    from ulid import ULID

    item_id = await _make_item(client, "ListedDeact")
    source_id = await _make_source(client, "https://example.com/deact")
    await _bind(client, item_id, source_id)

    binding = await session.get(
        InfoItemSource,
        (ULID.from_str(item_id), ULID.from_str(source_id)),
    )
    binding.deactivated_at = datetime.now(UTC)
    await session.flush()

    body = (await client.get("/api/v1/info-items", headers=HEADERS)).json()
    item_out = next(i for i in body["items"] if i["info_item_id"] == item_id)
    assert item_out["info_item_sources"] == []
