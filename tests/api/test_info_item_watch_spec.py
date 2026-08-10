"""WatchSpec read + write surface on InfoItem (archiver#150)."""

import pytest
from ulid import ULID

HEADERS = {"X-API-Key": "test-secret-key"}

DEFAULT = {"schema_version": 1, "active": True}


async def _make_item(client, name: str = "Item") -> str:
    return (await client.post("/api/v1/info-items", headers=HEADERS, json={"name": name})).json()[
        "info_item_id"
    ]


@pytest.mark.asyncio
async def test_get_info_item_returns_the_default_watch_spec(client):
    item_id = await _make_item(client)
    response = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["watch_spec"] == DEFAULT


@pytest.mark.asyncio
async def test_put_watch_spec_replaces_the_document(client):
    item_id = await _make_item(client)
    doc = {"schema_version": 1, "active": False, "interval": "6h"}

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec", headers=HEADERS, json={"document": doc}
    )

    assert response.status_code == 200
    assert response.json()["watch_spec"] == doc
    reread = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert reread.json()["watch_spec"] == doc


@pytest.mark.asyncio
async def test_put_watch_spec_accepts_a_document_without_an_interval(client):
    """Absent interval is the way to say 'consumer applies its default'."""
    item_id = await _make_item(client)
    doc = {"schema_version": 1, "active": True}

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec", headers=HEADERS, json={"document": doc}
    )

    assert response.status_code == 200
    assert "interval" not in response.json()["watch_spec"]


@pytest.mark.asyncio
async def test_put_watch_spec_clears_a_previously_set_interval(client):
    """PUT replaces the whole document — it is not a merge."""
    item_id = await _make_item(client)
    await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "active": True, "interval": "1h"}},
    )

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "active": True}},
    )

    assert response.status_code == 200
    assert response.json()["watch_spec"] == {"schema_version": 1, "active": True}


@pytest.mark.asyncio
async def test_put_watch_spec_rejects_an_invalid_document_with_422_envelope(client):
    item_id = await _make_item(client)

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "active": True, "interval": "daily"}},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "schema"
    assert any(e["path"] == "/interval" for e in detail["errors"])


@pytest.mark.asyncio
async def test_put_watch_spec_leaves_the_stored_document_untouched_when_invalid(client):
    item_id = await _make_item(client)
    await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "active": False, "interval": "7d"}},
    )

    await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"active": True}},
    )

    reread = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert reread.json()["watch_spec"] == {
        "schema_version": 1,
        "active": False,
        "interval": "7d",
    }


@pytest.mark.asyncio
async def test_put_watch_spec_404s_for_an_unknown_item(client):
    response = await client.put(
        f"/api/v1/info-items/{ULID()}/watch-spec",
        headers=HEADERS,
        json={"document": DEFAULT},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_put_watch_spec_requires_an_api_key(client):
    """Missing key is 403, matching tests/api/test_auth.py; a wrong key is 401."""
    item_id = await _make_item(client)

    missing = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec", json={"document": DEFAULT}
    )
    wrong = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers={"X-API-Key": "nope"},
        json={"document": DEFAULT},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 401
