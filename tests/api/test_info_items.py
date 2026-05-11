"""InfoItem CRUD route tests."""

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}


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
async def test_get_info_item_404(client):
    response = await client.get("/api/v1/info-items/01HZZZZZZZZZZZZZZZZZZZZZZZ", headers=HEADERS)
    assert response.status_code == 404


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
