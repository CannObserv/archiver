"""Every registry mutation route emits an ``info.registry`` delta (archiver#141).

One test per emit site, plus the invariants that are route-shaped rather than
service-shaped: a swap announces exactly **once** with the final state (two
announcements would be revoked-then-live and the consumer would destroy and
recreate its row), and the DELETE tombstone rides the deletion's transaction.

Deliberate non-sites, pinned by tests where silence is load-bearing:

- ``POST /info-sources`` — a fresh source has no bindings, so there is no
  announced state to change.
- Dashboard ``toggle-watch-active`` — still SDK-only until the epic's step-6
  control-plane cutover; it does not mutate ``info_items.watch_active``, so it
  has nothing to announce yet.
"""

import pytest
from sqlalchemy import select
from ulid import ULID

from src.core.models import ChangesOutboxRow, InfoItem, InfoSource, RevokedInfoItem
from src.core.models.domain import Domain

HEADERS = {"X-API-Key": "test-secret-key"}
DASH_HEADERS = {"X-ExeDev-UserID": "ext-emit", "X-ExeDev-Email": "emit@example.com"}

_FULL_PAGE_SPECS_JSON = (
    '[{"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}]'
)

_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": "body"},
    "fingerprint": {},
}


async def _registry_rows(session) -> list[dict]:
    result = await session.execute(
        select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.registry")
    )
    return list(result.scalars())


async def _make_bound_item(client) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "Emit",
            "initial_url": "https://example.com/a",
            "initial_source_specs": [_SPEC],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["info_item_id"], body["info_item_sources"][0]["info_source_id"]


# --- API routes -------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_with_initial_url_announces_live(client, session):
    item_id, source_id = await _make_bound_item(client)

    (payload,) = await _registry_rows(session)
    assert payload["info_item_id"] == item_id
    assert payload["info_source_id"] == source_id
    assert payload["revoked"] is False
    assert payload["generation"] == 1


@pytest.mark.asyncio
async def test_bare_create_announces_nothing(client, session):
    resp = await client.post("/api/v1/info-items", headers=HEADERS, json={"name": "Bare"})
    assert resp.status_code == 201

    assert await _registry_rows(session) == []


@pytest.mark.asyncio
async def test_bind_announces_live(client, session):
    resp = await client.post("/api/v1/info-items", headers=HEADERS, json={"name": "B"})
    item_id = resp.json()["info_item_id"]
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://example.com/b", "source_specs": [_SPEC]},
    )
    source_id = resp.json()["info_source_id"]

    resp = await client.post(
        f"/api/v1/info-items/{item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": source_id},
    )
    assert resp.status_code == 201

    rows = await _registry_rows(session)
    assert len(rows) == 1
    assert rows[0]["info_source_id"] == source_id
    assert rows[0]["revoked"] is False


@pytest.mark.asyncio
async def test_binding_deactivation_announces_revoked(client, session):
    item_id, source_id = await _make_bound_item(client)

    resp = await client.delete(
        f"/api/v1/info-items/{item_id}/info-sources/{source_id}", headers=HEADERS
    )
    assert resp.status_code == 200

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert len(rows) == 2
    assert rows[1]["revoked"] is True
    assert rows[1]["generation"] == 2


@pytest.mark.asyncio
async def test_watch_spec_put_announces(client, session):
    item_id, _ = await _make_bound_item(client)

    resp = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "interval": "6h"}},
    )
    assert resp.status_code == 200

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert rows[-1]["watch_spec"] == {"schema_version": 1, "interval": "6h"}


@pytest.mark.asyncio
async def test_watch_spec_validation_failure_announces_nothing(client, session):
    item_id, _ = await _make_bound_item(client)
    before = len(await _registry_rows(session))

    resp = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "active": False}},
    )
    assert resp.status_code == 422

    assert len(await _registry_rows(session)) == before


@pytest.mark.asyncio
async def test_watch_active_put_announces(client, session):
    item_id, _ = await _make_bound_item(client)

    resp = await client.put(
        f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={"active": False}
    )
    assert resp.status_code == 200

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert rows[-1]["active"] is False


@pytest.mark.asyncio
async def test_source_spec_patch_fans_out_to_bound_items(client, session):
    item_id, source_id = await _make_bound_item(client)

    new_specs = [
        {
            "schema_version": 1,
            "extraction": {"algorithm": "css", "selector": "main"},
            "fingerprint": {},
        }
    ]
    resp = await client.patch(
        f"/api/v1/info-sources/{source_id}/source-specs",
        headers=HEADERS,
        json={"source_specs": new_specs},
    )
    assert resp.status_code == 200

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert rows[-1]["source_specs"] == new_specs
    assert rows[-1]["info_item_id"] == item_id


@pytest.mark.asyncio
async def test_source_create_announces_nothing(client, session):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={"url": "https://example.com/lonely", "source_specs": [_SPEC]},
    )
    assert resp.status_code == 201

    assert await _registry_rows(session) == []


@pytest.mark.asyncio
async def test_delete_announces_tombstone_and_records_it(client, session):
    item_id, _ = await _make_bound_item(client)

    resp = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert resp.status_code == 204

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert rows[-1]["revoked"] is True
    revoked = (
        await session.execute(
            select(RevokedInfoItem).where(RevokedInfoItem.info_item_id == ULID.from_str(item_id))
        )
    ).scalar_one()
    assert revoked.generation == rows[-1]["generation"]


# --- Dashboard routes -------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_create_with_url_announces(client, session):
    resp = await client.post(
        "/dashboard/info-items/new",
        headers=DASH_HEADERS,
        data={
            "name": "Dash Item",
            "initial_url": "https://example.com/dash",
            "initial_source_specs": _FULL_PAGE_SPECS_JSON,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text

    rows = await _registry_rows(session)
    assert len(rows) == 1
    assert rows[0]["revoked"] is False


@pytest.mark.asyncio
async def test_dashboard_bind_source_announces(client, session):
    item = InfoItem(name="DashBind")
    source = InfoSource(url="https://example.com/db", source_specs=[_SPEC])
    session.add_all([item, source])
    await session.flush()

    resp = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/bind-source",
        headers=DASH_HEADERS,
        data={"info_source_id": str(source.info_source_id)},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    rows = await _registry_rows(session)
    assert len(rows) == 1
    assert rows[0]["info_item_id"] == str(item.info_item_id)


@pytest.mark.asyncio
async def test_dashboard_binding_deactivation_announces(client, session):
    item_id, source_id = await _make_bound_item(client)

    resp = await client.delete(
        f"/dashboard/info-items/{item_id}/info-sources/{source_id}",
        headers=DASH_HEADERS,
    )
    assert resp.status_code == 200

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert rows[-1]["revoked"] is True


@pytest.mark.asyncio
async def test_dashboard_swap_announces_exactly_once_with_final_state(client, session):
    """The swap deactivates the old binding AND creates the new one in a single
    transaction — one mutation flow, one announcement, carrying the new source.
    Two announcements would be revoked-then-live: the consumer would delete its
    WatchedItem (losing applied_generation, its name, every local column) and
    recreate it moments later."""
    item_id, old_source_id = await _make_bound_item(client)

    resp = await client.post(
        f"/dashboard/info-items/{item_id}/swap-primary-source",
        headers=DASH_HEADERS,
        data={
            "url": "https://example.com/swapped",
            "source_specs": _FULL_PAGE_SPECS_JSON,
        },
    )
    assert resp.status_code == 204, resp.text

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert len(rows) == 2  # the create's live announcement + ONE for the swap
    assert rows[-1]["revoked"] is False
    assert rows[-1]["url"] == "https://example.com/swapped"
    assert rows[-1]["info_source_id"] != old_source_id


@pytest.mark.asyncio
async def test_dashboard_swap_by_id_announces_exactly_once(client, session):
    item_id, _ = await _make_bound_item(client)
    new_source = InfoSource(url="https://example.com/by-id", source_specs=[_SPEC])
    session.add(new_source)
    await session.flush()

    resp = await client.post(
        f"/dashboard/info-items/{item_id}/swap-primary-by-id",
        headers=DASH_HEADERS,
        data={"info_source_id": str(new_source.info_source_id)},
    )
    assert resp.status_code == 204, resp.text

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert len(rows) == 2
    assert rows[-1]["revoked"] is False
    assert rows[-1]["info_source_id"] == str(new_source.info_source_id)


@pytest.mark.asyncio
async def test_dashboard_source_spec_edit_fans_out(client, session):
    item_id, source_id = await _make_bound_item(client)

    resp = await client.post(
        f"/dashboard/info-sources/{source_id}/source-specs",
        headers=DASH_HEADERS,
        data={"source_specs": _FULL_PAGE_SPECS_JSON},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303), resp.text

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert rows[-1]["info_item_id"] == item_id
    assert rows[-1]["source_specs"][0]["extraction"]["algorithm"] == "full_page"


@pytest.mark.asyncio
async def test_dashboard_register_announces(client, session):
    session.add(Domain(name="example.com"))
    await session.flush()

    resp = await client.post(
        "/dashboard/register",
        headers=DASH_HEADERS,
        data={
            "name": "Registered",
            "url": "https://example.com/reg",
            "source_specs": _FULL_PAGE_SPECS_JSON,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text

    rows = await _registry_rows(session)
    assert len(rows) == 1
    assert rows[0]["revoked"] is False
