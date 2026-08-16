"""Every registry mutation route emits an ``info.registry`` delta (archiver#141).

One test per emit site, plus the invariants that are route-shaped rather than
service-shaped: a swap announces exactly **once** with the final state (two
announcements would be revoked-then-live and the consumer would destroy and
recreate its row), and the DELETE tombstone rides the deletion's transaction.

Deliberate non-sites, pinned by tests where silence is load-bearing:

- ``POST /info-sources`` — a fresh source has no bindings, so there is no
  announced state to change.
(``toggle-watch-active`` used to be listed here as SDK-only with nothing to
announce. The step-6 control-plane cutover, archiver#158, made it a local write
plus an announcement — it is now covered below.)
"""

import pytest
from sqlalchemy import select
from ulid import ULID

from src.core.models import ChangesOutboxRow, InfoItem, InfoSource, RevokedInfoItem
from src.core.models.domain import Domain
from src.core.watch_spec_schema.validator import DEFAULT_WATCH_SPEC

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


@pytest.mark.asyncio
async def test_dashboard_toggle_watch_active_announces_the_new_state(client, session):
    """archiver#158: pause/resume is a local write plus an announcement.

    Before the cutover this endpoint only PATCHed Watcher and mutated nothing
    locally, so it had nothing to announce. It is now the control plane.
    """
    item_id, _source_id = await _make_bound_item(client)

    resp = await client.post(
        f"/dashboard/info-items/{item_id}/toggle-watch-active",
        headers=DASH_HEADERS,
        data={"active": "false"},
    )
    assert resp.status_code == 200, resp.text

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert len(rows) == 2  # the create's live announcement + the pause
    assert rows[-1]["active"] is False
    assert rows[-1]["revoked"] is False

    item = (
        await session.execute(
            select(InfoItem).where(InfoItem.info_item_id == ULID.from_str(item_id))
        )
    ).scalar_one()
    await session.refresh(item)
    assert item.watch_active is False


@pytest.mark.asyncio
async def test_dashboard_toggle_watch_active_resume_announces_true(client, session):
    item_id, _source_id = await _make_bound_item(client)

    await client.post(
        f"/dashboard/info-items/{item_id}/toggle-watch-active",
        headers=DASH_HEADERS,
        data={"active": "false"},
    )
    resp = await client.post(
        f"/dashboard/info-items/{item_id}/toggle-watch-active",
        headers=DASH_HEADERS,
        data={"active": "true"},
    )
    assert resp.status_code == 200

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert [r["active"] for r in rows[-2:]] == [False, True]


@pytest.mark.asyncio
async def test_dashboard_register_announces_the_chosen_cadence_and_pause_state(client, session):
    """archiver#158: registration writes Archiver's policy, not Watcher's.

    Before the cutover the form's cadence went out as ``schedule_config`` on the
    provisioning call and ``watch_spec`` kept its column default, so the very
    first announcement disagreed with what the operator picked.
    """
    resp = await client.post(
        "/dashboard/register",
        headers=DASH_HEADERS,
        data={
            "url": "https://example.com/register-policy",
            "source_specs": _FULL_PAGE_SPECS_JSON,
            "name": "Policy At Registration",
            "description": "",
            "cadence": "6h",
            # watch_active checkbox absent → registered paused
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text

    rows = await _registry_rows(session)
    assert len(rows) == 1
    assert rows[0]["watch_spec"] == {"schema_version": 1, "interval": "6h"}
    assert rows[0]["active"] is False


@pytest.mark.asyncio
async def test_dashboard_register_falls_back_to_the_default_spec(client, session):
    """An unrecognised cadence must not fabricate an interval — the column
    default stands, which spells 'delegate to the consumer's own default'."""
    resp = await client.post(
        "/dashboard/register",
        headers=DASH_HEADERS,
        data={
            "url": "https://example.com/register-default",
            "source_specs": _FULL_PAGE_SPECS_JSON,
            "name": "Default Cadence",
            "description": "",
            "cadence": "not-an-option",
            "watch_active": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text

    rows = await _registry_rows(session)
    assert len(rows) == 1
    assert rows[0]["watch_spec"] == DEFAULT_WATCH_SPEC
    assert rows[0]["active"] is True


@pytest.mark.asyncio
async def test_dashboard_set_cadence_announces(client, session):
    """archiver#158: post-registration cadence is editable, and it announces.

    Before the cutover cadence was display-only after registration — there was
    no affordance at all, because the value lived in Watcher.
    """
    item_id, _source_id = await _make_bound_item(client)

    resp = await client.post(
        f"/dashboard/info-items/{item_id}/watch-cadence",
        headers=DASH_HEADERS,
        data={"interval": "7d"},
    )
    assert resp.status_code == 200, resp.text

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert rows[-1]["watch_spec"] == {"schema_version": 1, "interval": "7d"}


@pytest.mark.asyncio
async def test_dashboard_set_cadence_to_delegate_drops_the_interval(client, session):
    """The empty selection is the only way to say 'use your own default' — a
    merge-style edit would make that state unreachable once an interval is set."""
    item_id, _source_id = await _make_bound_item(client)
    await client.post(
        f"/dashboard/info-items/{item_id}/watch-cadence",
        headers=DASH_HEADERS,
        data={"interval": "1h"},
    )

    resp = await client.post(
        f"/dashboard/info-items/{item_id}/watch-cadence",
        headers=DASH_HEADERS,
        data={"interval": ""},
    )
    assert resp.status_code == 200

    rows = sorted(await _registry_rows(session), key=lambda p: p["generation"])
    assert rows[-1]["watch_spec"] == {"schema_version": 1}


@pytest.mark.asyncio
async def test_dashboard_set_cadence_rejects_an_unoffered_value(client, session):
    """The dropdown is a closed vocabulary; a hand-posted value must not write."""
    item_id, _source_id = await _make_bound_item(client)
    before = len(await _registry_rows(session))

    resp = await client.post(
        f"/dashboard/info-items/{item_id}/watch-cadence",
        headers=DASH_HEADERS,
        data={"interval": "3f"},
    )
    assert resp.status_code == 200  # partial re-render, not a 4xx — HTMX target
    assert "showFlash" in resp.headers.get("HX-Trigger", "")
    assert len(await _registry_rows(session)) == before
