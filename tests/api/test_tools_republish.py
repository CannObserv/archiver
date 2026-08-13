"""POST /tools/republish-registry-announcements — the operator's "republish now".

The snapshot loop owns the actual publish; the route only sets the trigger
event the loop waits on, so a republish request is asynchronous by design (202)
and cannot block an HTTP worker on a full-set publish.
"""

import asyncio

import pytest

from src.api.main import app

HEADERS = {"X-API-Key": "test-secret-key"}
URL = "/api/v1/tools/republish-registry-announcements"


@pytest.mark.asyncio
async def test_republish_sets_the_snapshot_trigger(client):
    trigger = asyncio.Event()
    app.state.registry_snapshot_trigger = trigger
    try:
        resp = await client.post(URL, headers=HEADERS)
        assert resp.status_code == 202
        assert resp.json() == {"triggered": True}
        assert trigger.is_set()
    finally:
        app.state.registry_snapshot_trigger = None


@pytest.mark.asyncio
async def test_republish_conflicts_when_bus_dormant(client):
    """No trigger means no snapshot loop (dev server without a bus URL) — a 409
    envelope, not a silent 202 that never publishes anything."""
    app.state.registry_snapshot_trigger = None
    resp = await client.post(URL, headers=HEADERS)
    assert resp.status_code == 409
    assert resp.json()["detail"]["kind"] == "conflict"


@pytest.mark.asyncio
async def test_republish_requires_an_api_key(client):
    resp = await client.post(URL)
    assert resp.status_code in (401, 403)
