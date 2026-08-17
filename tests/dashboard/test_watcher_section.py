"""Tests for the Section 3 Watcher panel (GET /watcher-section).

Covers:
  GET  /dashboard/info-items/{id}/watcher-section
  HX-Trigger: watcherUpdated on the surviving control-plane actions

The panel's *render* went local in archiver#151; archiver#142 removed the SDK
its action buttons still rode, so nothing here mocks a Watcher client any more.
The state key moved with it: a panel is `watching` because the item is in the
announced set (an active binding whose source carries non-empty specs), not
because a `watcher_item_id` was once written. Hence `bind_source` on every test
that expects a watched state — an unbound item is `not_watching` by definition.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.models import InfoItem, WatchStatus

_HEADERS = {"X-ExeDev-UserID": "ext-section", "X-ExeDev-Email": "section@example.com"}
_STATUS_TS = datetime(2026, 6, 11, 11, 0, tzinfo=UTC)


def _seed_status(session, item: InfoItem, **overrides) -> None:
    """Seed the local watch_status cache the panel renders from (archiver#151)."""
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


async def _section(client, item: InfoItem):
    return await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )


# ---------------------------------------------------------------------------
# GET /watcher-section — not watching (outside the announced set)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_not_watching_when_unbound(client, session):
    """No active binding → not in the announced set → not watched.

    Before archiver#142 this keyed on `watcher_item_id`. The distinction matters:
    an unbound item never reaches Watcher at all, so `not_watching` is now a
    statement about the registry rather than about a remote row.
    """
    item = InfoItem(name="section-not-watching")
    session.add(item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "watcher-section" in r.text
    assert "Not watching" in r.text
    # The provisioning affordance is gone — watching is a consequence, not an action.
    assert "begin-watching" not in r.text
    # ...replaced by a statement of what would close the gap.
    assert "bind an active source" in r.text


@pytest.mark.asyncio
async def test_watcher_section_not_watching_when_bound_source_has_no_specs(
    client, session, bind_source
):
    """Bound but unannounceable is the other half of the gate.

    A source with empty `source_specs` is announced as a *tombstone*, so the item
    is not watched even though a binding exists. The panel must agree with the
    announcement rather than with the binding alone.
    """
    item = InfoItem(name="section-specless")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-specless", specs=[])
    _seed_status(session, item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "Not watching" in r.text


# ---------------------------------------------------------------------------
# GET /watcher-section — watching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_watching_shows_details(client, session, bind_source):
    item = InfoItem(name="section-watching")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-watching")
    _seed_status(session, item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "watcher-section" in r.text
    # Health badge
    assert "OK" in r.text
    # The URL and the Watcher deeplink moved off the section (#62): URL lives in
    # the Information Sources section. The deeplink itself retired in #142.
    assert "https://example.com/page" not in r.text
    assert "View in Watcher" not in r.text
    # The SDK-backed actions are gone; the local control plane remains.
    assert "check-now" not in r.text
    assert "resync-watcher" not in r.text
    assert "toggle-watch-active" in r.text
    assert "Pause" in r.text


@pytest.mark.asyncio
async def test_watcher_section_paused_shows_resume(client, session, bind_source):
    item = InfoItem(name="section-paused")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-paused")
    _seed_status(session, item, applied_active=False)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "toggle-watch-active" in r.text
    assert "Resume" in r.text
    assert "Paused" in r.text


@pytest.mark.asyncio
async def test_pause_affordance_absent_without_an_announceable_source(client, session, bind_source):
    """Announcing a pause for an unannounceable item burns a generation for
    nothing (CR round 1, finding 3) — so the control is withheld, not merely
    ineffective."""
    item = InfoItem(name="section-pause-gated")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-pause-gated", specs=[])
    _seed_status(session, item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "toggle-watch-active" not in r.text


# ---------------------------------------------------------------------------
# GET /watcher-section — no status yet: the fourth state (archiver#151)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_no_status_yet(client, session, bind_source):
    """Announced, but Watcher has never reported. Distinct from both
    `not_watching` and `watching` — #151's contract, unchanged by #142."""
    item = InfoItem(name="section-silent")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-silent")
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "NO STATUS YET" in r.text
    assert "Paused" not in r.text
    assert "Not watching" not in r.text


@pytest.mark.asyncio
async def test_watcher_section_omits_spec_row(client, session, bind_source):
    """Spec now lives in the Information Sources section, not here (#62)."""
    item = InfoItem(name="section-no-spec")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-no-spec")
    _seed_status(session, item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "Spec" not in r.text


@pytest.mark.asyncio
async def test_watcher_section_carries_auto_refresh_trigger(client, session, bind_source):
    item = InfoItem(name="section-auto-refresh")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-auto-refresh")
    _seed_status(session, item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "watcherUpdated" in r.text


# ---------------------------------------------------------------------------
# HX-Trigger on the surviving control-plane action (pause/resume)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_watch_active_triggers_watcher_updated(client, session, bind_source):
    """The section self-refreshes off `watcherUpdated`; the SDK actions that used
    to fire it are gone, so the local control plane must still send it."""
    item = InfoItem(name="toggle-trigger")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="toggle-trigger")
    _seed_status(session, item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    assert "watcherUpdated" in r.headers.get("HX-Trigger", "")


# ---------------------------------------------------------------------------
# The cadence editor — new in archiver#158 (post-registration cadence was
# display-only before the control-plane cutover)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_renders_the_cadence_editor_with_the_announced_value(
    client, session, bind_source
):
    item = InfoItem(
        name="section-cadence",
        watch_spec={"schema_version": 1, "interval": "6h"},
    )
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-cadence")
    _seed_status(session, item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "watch-cadence" in r.text
    # The announced interval is the selected option, not merely present.
    assert '<option value="6h" selected>' in r.text
    # "Delegate" stays reachable — it is the only way back to the consumer default.
    assert 'value="" selected' not in r.text
    assert "Consumer default" in r.text


@pytest.mark.asyncio
async def test_cadence_editor_selects_delegate_when_no_interval_is_announced(
    client, session, bind_source
):
    item = InfoItem(name="section-cadence-delegate", watch_spec={"schema_version": 1})
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-cadence-delegate")
    _seed_status(session, item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert '<option value="" selected>' in r.text


@pytest.mark.asyncio
async def test_cadence_editor_renders_before_watcher_has_ever_reported(
    client, session, bind_source
):
    """The `no_status` state offers it too (CR round 1, finding 1).

    A freshly registered item sits here until Watcher's first status frame, and
    that is precisely when an operator wants to revise the cadence they just
    picked. The editor previously rendered only under `watching`, so the window
    the affordance was added for was the one window it was missing from.
    """
    item = InfoItem(name="section-cadence-nostatus")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug="section-cadence-nostatus")
    # no _seed_status -> no_status

    r = await _section(client, item)
    assert r.status_code == 200
    assert "NO STATUS YET" in r.text
    assert "watch-cadence" in r.text


@pytest.mark.asyncio
async def test_cadence_editor_absent_when_not_watching(client, session):
    """`not_watching` has no announceable source by definition, so there is no
    cadence that could take effect."""
    item = InfoItem(name="section-cadence-unwatched")
    session.add(item)
    await session.flush()

    r = await _section(client, item)
    assert r.status_code == 200
    assert "Not watching" in r.text
    assert "watch-cadence" not in r.text
