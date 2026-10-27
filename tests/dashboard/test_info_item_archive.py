"""Watch lifecycle on the dashboard: archive and restore an InfoItem (archiver#361).

Archive and Restore are plain POSTs that 303 back to the detail page (the
Domain precedent, #360), so the Overview badge and the panel re-render
together. Once archived, both partials replace Pause/Resume with "Archived ·
Restore" - a toggle there would write a ``watch_active`` the wire ignores until
restore - and the applied pause never reads as a pending resume.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ulid import ULID

from src.core.models import InfoItem, WatchStatus

_HEADERS = {"X-ExeDev-UserID": "ext-archive", "X-ExeDev-Email": "archive@example.com"}
_TS = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
_PARTIALS = ["watcher-section", "watcher-status"]


async def _item(session, bind_source, *, archived: bool, bound: bool = True, status: bool = True):
    item = InfoItem(name="archivable", watch_active=True, archived_at=_TS if archived else None)
    session.add(item)
    await session.flush()
    if bound:
        await bind_source(session, item, slug=f"archive-{item.info_item_id}")
    if bound and status:
        session.add(
            WatchStatus(
                info_item_id=item.info_item_id,
                applied_generation=item.announcement_generation,
                applied_active=not archived,
                applied_interval=None,
                last_attempt_at=_TS,
                last_observed_at=_TS,
                health="ok",
                occurred_at=_TS,
            )
        )
    await session.flush()
    return item


async def _get(client, item, partial: str):
    r = await client.get(f"/dashboard/info-items/{item.info_item_id}/{partial}", headers=_HEADERS)
    assert r.status_code == 200
    return r.text


# --- The panel -----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", _PARTIALS)
async def test_an_archived_item_offers_restore_instead_of_the_toggle(
    client, session, bind_source, partial
):
    item = await _item(session, bind_source, archived=True)

    text = await _get(client, item, partial)

    assert "Archived" in text
    assert f'action="/dashboard/info-items/{item.info_item_id}/restore"' in text
    assert "toggle-watch-active" not in text
    assert "pending" not in text  # applied false is the announced state


@pytest.mark.asyncio
async def test_an_unarchived_watched_item_offers_archive_beside_the_toggle(
    client, session, bind_source
):
    item = await _item(session, bind_source, archived=False)

    text = await _get(client, item, "watcher-section")

    assert "toggle-watch-active" in text
    assert f'action="/dashboard/info-items/{item.info_item_id}/archive"' in text
    assert "/restore" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bound", "status", "state"),
    [(False, False, "Not watching"), (True, False, "NO STATUS YET")],
)
@pytest.mark.parametrize("archived", [True, False])
async def test_the_lifecycle_control_renders_outside_the_watching_state(
    client, session, bind_source, bound, status, state, archived
):
    """Archive stores state on any item (D2, #167), so it is offered in every
    state but ``degraded``, not only where Pause is."""
    item = await _item(session, bind_source, archived=archived, bound=bound, status=status)

    text = await _get(client, item, "watcher-section")

    assert state in text
    action = "restore" if archived else "archive"
    assert f'action="/dashboard/info-items/{item.info_item_id}/{action}"' in text


# --- The routes ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_and_restore_redirect_to_the_detail_page(client, session, bind_source):
    item = await _item(session, bind_source, archived=False)
    detail = f"/dashboard/info-items/{item.info_item_id}"

    archived = await client.post(f"{detail}/archive", headers=_HEADERS, follow_redirects=False)
    assert archived.status_code == 303
    assert archived.headers["location"] == detail
    await session.refresh(item)
    assert item.archived_at is not None
    assert item.watch_active is True

    restored = await client.post(f"{detail}/restore", headers=_HEADERS, follow_redirects=False)
    assert restored.status_code == 303
    await session.refresh(item)
    assert item.archived_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["archive", "restore"])
async def test_a_missing_item_is_a_404(client, action):
    r = await client.post(f"/dashboard/info-items/{ULID()}/{action}", headers=_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_toggling_an_archived_item_stores_the_intent(client, session, bind_source):
    """D3: a stale tab or a script may still post the toggle; it is accepted."""
    item = await _item(session, bind_source, archived=True)

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )

    assert r.status_code == 200
    await session.refresh(item)
    assert item.watch_active is False
    assert item.archived_at is not None


# --- The badges ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [True, False])
async def test_the_detail_overview_badges_an_archived_item(client, session, bind_source, archived):
    item = await _item(session, bind_source, archived=archived, bound=False)

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert ('<span class="badge badge--warning">archived</span>' in r.text) is archived


@pytest.mark.asyncio
async def test_the_list_badges_an_archived_item_and_keeps_listing_it(client, session, bind_source):
    """D4: archived items stay listed (the Domain list's precedent)."""
    kept = await _item(session, bind_source, archived=False, bound=False)
    kept.name = "list-kept-361"
    gone = await _item(session, bind_source, archived=True, bound=False)
    gone.name = "list-gone-361"
    await session.flush()

    r = await client.get("/dashboard/info-items/?name_contains=-361", headers=_HEADERS)

    assert r.status_code == 200
    assert "list-kept-361" in r.text
    assert "list-gone-361" in r.text
    assert r.text.count('<span class="badge badge--warning">archived</span>') == 1
