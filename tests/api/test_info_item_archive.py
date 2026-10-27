"""Watch lifecycle over the API: archive and restore an InfoItem (archiver#361).

``POST /info-items/{id}/archive`` and ``/restore`` are the Domain routes'
shape (#360). ``archived_at`` rides ``InfoItemOut``, and ``GET /info-items``
filters on it, defaulting to all.
"""

import pytest
from sqlalchemy import select
from ulid import ULID

from src.core.models import ChangesOutboxRow

HEADERS = {"X-API-Key": "test-secret-key"}

_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": "body"},
    "fingerprint": {},
}


async def _make_item(client, name: str = "Archivable", *, bound: bool = True) -> str:
    body: dict = {"name": name}
    if bound:
        body |= {"initial_url": "https://archive.example.com/a", "initial_source_specs": [_SPEC]}
    resp = await client.post("/api/v1/info-items", headers=HEADERS, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["info_item_id"]


async def _active(session, item_id: str) -> list[bool | None]:
    """The item's announced ``active`` values, in generation order."""
    rows = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.registry")
        )
    ).scalars()
    mine = sorted((p for p in rows if p["info_item_id"] == item_id), key=lambda p: p["generation"])
    return [p["active"] for p in mine]


@pytest.mark.asyncio
async def test_archive_sets_archived_at_and_announces_inactive(client, session):
    item_id = await _make_item(client)
    await client.put(
        f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={"active": True}
    )

    resp = await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["archived_at"] is not None
    assert body["watch_active"] is True  # D1: archive is not a pause
    assert await _active(session, item_id) == [None, True, False]


@pytest.mark.asyncio
async def test_a_second_archive_keeps_the_timestamp_and_announces_nothing(client, session):
    item_id = await _make_item(client)
    first = (await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)).json()

    again = await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)

    assert again.status_code == 200
    assert again.json()["archived_at"] == first["archived_at"]
    assert await _active(session, item_id) == [None, False]


@pytest.mark.asyncio
@pytest.mark.parametrize("watch_active", [True, False])
async def test_restore_returns_the_item_to_its_own_state(client, session, watch_active):
    item_id = await _make_item(client)
    await client.put(
        f"/api/v1/info-items/{item_id}/watch-active",
        headers=HEADERS,
        json={"active": watch_active},
    )
    await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)

    resp = await client.post(f"/api/v1/info-items/{item_id}/restore", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None
    assert (await _active(session, item_id))[-2:] == [False, watch_active]


@pytest.mark.asyncio
async def test_restore_of_an_unarchived_item_is_a_no_op(client, session):
    item_id = await _make_item(client)

    resp = await client.post(f"/api/v1/info-items/{item_id}/restore", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None
    assert await _active(session, item_id) == [None]


@pytest.mark.asyncio
async def test_an_unannounceable_item_archives_without_announcing(client, session):
    item_id = await _make_item(client, bound=False)

    resp = await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)

    assert resp.json()["archived_at"] is not None
    assert await _active(session, item_id) == []


@pytest.mark.asyncio
async def test_watch_active_on_an_archived_item_is_stored_and_the_wire_stays_inactive(
    client, session
):
    """D3: the API accepts intent while archived; restore applies it."""
    item_id = await _make_item(client)
    await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)

    resp = await client.put(
        f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={"active": True}
    )
    assert resp.status_code == 200
    assert resp.json()["watch_active"] is True
    await client.post(f"/api/v1/info-items/{item_id}/restore", headers=HEADERS)

    assert await _active(session, item_id) == [None, False, False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [False, True])
async def test_delete_tombstones_whether_or_not_archived(client, session, archived):
    """Delete stays the revoked tombstone: Watcher's archive-first rule is dropped,
    and archiving first changes nothing about it (CR 12)."""
    item_id = await _make_item(client)
    if archived:
        await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)

    resp = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)

    assert resp.status_code == 204
    rows = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.registry")
        )
    ).scalars()
    last = max((p for p in rows if p["info_item_id"] == item_id), key=lambda p: p["generation"])
    assert last["revoked"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["archive", "restore"])
async def test_a_missing_item_is_a_404_envelope(client, action):
    resp = await client.post(f"/api/v1/info-items/{ULID()}/{action}", headers=HEADERS)

    assert resp.status_code == 404
    assert resp.json()["detail"]["kind"] == "lookup"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["archive", "restore"])
async def test_the_routes_require_an_api_key(client, action):
    item_id = await _make_item(client, bound=False)

    missing = await client.post(f"/api/v1/info-items/{item_id}/{action}")
    wrong = await client.post(
        f"/api/v1/info-items/{item_id}/{action}", headers={"X-API-Key": "nope"}
    )

    assert missing.status_code == 403
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_get_reports_archived_at(client):
    item_id = await _make_item(client, bound=False)
    assert (await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)).json()[
        "archived_at"
    ] is None

    await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)

    reread = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert reread.json()["archived_at"] is not None


@pytest.mark.asyncio
async def test_list_filters_on_archived_and_defaults_to_all(client):
    kept = await _make_item(client, "kept", bound=False)
    gone = await _make_item(client, "gone", bound=False)
    await client.post(f"/api/v1/info-items/{gone}/archive", headers=HEADERS)

    async def ids(query: str) -> set[str]:
        resp = await client.get(f"/api/v1/info-items{query}", headers=HEADERS)
        assert resp.status_code == 200
        return {i["info_item_id"] for i in resp.json()["items"]} & {kept, gone}

    assert await ids("") == {kept, gone}
    assert await ids("?archived=true") == {gone}
    assert await ids("?archived=false") == {kept}
