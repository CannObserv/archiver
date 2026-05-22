"""Tests for dashboard_url field on InfoItem API responses.

dashboard_url is None when ARCHIVER_PUBLIC_BASE_URL is not set, and points to
the Archiver dashboard detail page when the env var is configured.
"""

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}


async def _make_item(client, name: str = "Dashboard URL Test Item") -> str:
    resp = await client.post("/api/v1/info-items", headers=HEADERS, json={"name": name})
    assert resp.status_code == 201
    return resp.json()["info_item_id"]


@pytest.mark.asyncio
async def test_get_info_item_dashboard_url_none_when_not_configured(client, monkeypatch):
    """dashboard_url is None when ARCHIVER_PUBLIC_BASE_URL is absent."""
    monkeypatch.delenv("ARCHIVER_PUBLIC_BASE_URL", raising=False)
    item_id = await _make_item(client)
    resp = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["dashboard_url"] is None


@pytest.mark.asyncio
async def test_get_info_item_dashboard_url_points_to_dashboard(client, monkeypatch):
    """dashboard_url reflects ARCHIVER_PUBLIC_BASE_URL + dashboard path."""
    monkeypatch.setenv("ARCHIVER_PUBLIC_BASE_URL", "https://archiver.example.com")
    item_id = await _make_item(client)
    resp = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["dashboard_url"] == f"https://archiver.example.com/info-items/{item_id}"


@pytest.mark.asyncio
async def test_get_info_item_dashboard_url_strips_trailing_slash(client, monkeypatch):
    """Trailing slash on ARCHIVER_PUBLIC_BASE_URL does not double-slash the URL."""
    monkeypatch.setenv("ARCHIVER_PUBLIC_BASE_URL", "https://archiver.example.com/")
    item_id = await _make_item(client)
    resp = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert resp.json()["dashboard_url"] == f"https://archiver.example.com/info-items/{item_id}"


@pytest.mark.asyncio
async def test_list_info_items_dashboard_url(client, monkeypatch):
    """List endpoint includes dashboard_url on each item."""
    monkeypatch.setenv("ARCHIVER_PUBLIC_BASE_URL", "https://archiver.example.com")
    item_id = await _make_item(client)
    resp = await client.get("/api/v1/info-items", headers=HEADERS)
    assert resp.status_code == 200
    match = next(i for i in resp.json()["items"] if i["info_item_id"] == item_id)
    assert match["dashboard_url"] == f"https://archiver.example.com/info-items/{item_id}"


@pytest.mark.asyncio
async def test_create_info_item_returns_dashboard_url(client, monkeypatch):
    """POST /info-items response includes dashboard_url when configured."""
    monkeypatch.setenv("ARCHIVER_PUBLIC_BASE_URL", "https://archiver.example.com")
    resp = await client.post("/api/v1/info-items", headers=HEADERS, json={"name": "Test Item"})
    assert resp.status_code == 201
    body = resp.json()
    assert (
        body["dashboard_url"] == f"https://archiver.example.com/info-items/{body['info_item_id']}"
    )


@pytest.mark.asyncio
async def test_find_info_items_dashboard_url(client, monkeypatch):
    """tools/find-info-items returns dashboard_url on each result."""
    monkeypatch.setenv("ARCHIVER_PUBLIC_BASE_URL", "https://archiver.example.com")
    item_id = await _make_item(client, "Colorado Licenses Dashboard URL Test")
    resp = await client.get(
        "/api/v1/tools/find-info-items?q=Colorado+Licenses+Dashboard", headers=HEADERS
    )
    assert resp.status_code == 200
    results = resp.json()
    match = next(i for i in results if i["info_item_id"] == item_id)
    assert match["dashboard_url"] == f"https://archiver.example.com/info-items/{item_id}"
