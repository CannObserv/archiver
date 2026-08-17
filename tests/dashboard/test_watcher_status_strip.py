"""Tests for the watched-item status strip (GET /watcher-status).

Covers:
  GET /dashboard/info-items/{id}/watcher-status
  the `degraded` state, which only a *local* write failure can reach

The strip is the compact sibling of the Section 3 panel: same context builder,
same four states, different markup. No page embeds it — it is reachable directly
and is the (discarded) response body of the two control-plane POSTs.

Its coverage moved here when archiver#142 deleted ``test_watcher_proxy.py``. That
suite was overwhelmingly SDK-proxy behaviour that retired with the SDK, but it
also happened to be the only place the strip's own render was exercised; the
render outlived the proxying, so the tests do too (CR round 1, finding 5).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import src.dashboard.routes.info_items as info_items_routes
from src.core.models import InfoItem, WatchStatus

_HEADERS = {"X-ExeDev-UserID": "ext-strip", "X-ExeDev-Email": "strip@example.com"}
_STATUS_TS = datetime(2026, 6, 11, 11, 0, tzinfo=UTC)


def _seed_status(session, item: InfoItem, **overrides) -> None:
    defaults = dict(
        info_item_id=item.info_item_id,
        applied_generation=item.announcement_generation,
        applied_active=True,
        applied_interval=None,
        last_attempt_at=_STATUS_TS,
        last_observed_at=_STATUS_TS,
        health="ok",
        occurred_at=_STATUS_TS,
    )
    defaults.update(overrides)
    session.add(WatchStatus(**defaults))


async def _strip(client, item: InfoItem):
    return await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )


# ---------------------------------------------------------------------------
# The three render states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strip_not_watching_names_what_closes_the_gap(client, session):
    """The affordance replacement archiver#142 owed.

    "Begin Watching" was a button; watching is now a consequence of registry
    state, so the strip has to *say* what would make the item watched. Deleting
    the button without this would be the silent-regression the issue forbids.
    """
    item = InfoItem(name="strip-not-watching")
    session.add(item)
    await session.flush()

    r = await _strip(client, item)
    assert r.status_code == 200
    assert "watcher-status-strip" in r.text
    assert "Not watching" in r.text
    assert "bind an active source" in r.text
    assert "begin-watching" not in r.text


@pytest.mark.asyncio
async def test_strip_no_status_when_announced_but_unreported(client, session, bind_source):
    item = InfoItem(name="strip-no-status")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="strip-no-status")
    await session.flush()

    r = await _strip(client, item)
    assert r.status_code == 200
    assert "NO STATUS YET" in r.text
    assert "Not watching" not in r.text


@pytest.mark.asyncio
async def test_strip_watching_shows_health_and_pause(client, session, bind_source):
    item = InfoItem(name="strip-watching")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="strip-watching")
    _seed_status(session, item)
    await session.flush()

    r = await _strip(client, item)
    assert r.status_code == 200
    assert "OK" in r.text
    assert "toggle-watch-active" in r.text
    # The SDK actions retired with the HTTP edge.
    assert "check-now" not in r.text
    assert "resync-watcher" not in r.text


# ---------------------------------------------------------------------------
# degraded — a LOCAL failure, and the copy has to say so
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_degraded_copy_blames_the_local_write_not_watcher(
    client, session, bind_source, monkeypatch
):
    """`degraded` is unreachable from anything Watcher does (CR round 1, finding 1).

    Since archiver#142 there is no outbound call to fail: the only path into this
    state is a local write failing, and both call sites pass "couldn't save the
    watch policy". Copy that says "Watcher unavailable" sends the operator to
    check a service that is not involved — the same class of miscue the teardown
    removed elsewhere.
    """
    item = InfoItem(name="strip-degraded")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="strip-degraded")
    _seed_status(session, item)
    await session.flush()

    def boom(*args, **kwargs):
        raise RuntimeError("announce failed")

    monkeypatch.setattr(info_items_routes, "announce_info_item", boom)

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    # Apostrophes are HTML-escaped in the render; match the unambiguous span.
    assert "watch policy write" in r.text
    assert "Watcher unavailable" not in r.text
