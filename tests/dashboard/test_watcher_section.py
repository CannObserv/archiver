"""Tests for the Section 3 Watcher panel (GET /watcher-section).

Covers:
  GET  /dashboard/info-items/{id}/watcher-section
  HX-Trigger: watcherUpdated on the surviving control-plane actions

The panel's *render* went local in archiver#151; archiver#142 removed the SDK
its action buttons still rode, so nothing here mocks a Watcher client any more.
The state key moved with it: a panel is `watching` because the item is in the
announced set (an active binding whose source carries non-empty specs), not
because a `watcher_item_id` was once written. Hence `bind_source` on every test
that expects a watched state - an unbound item is `not_watching` by definition.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.models import InfoItem, SourceRevision, WatchStatus

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
# GET /watcher-section - not watching (outside the announced set)
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
    # The provisioning affordance is gone - watching is a consequence, not an action.
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
# GET /watcher-section - watching
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
    nothing (CR round 1, finding 3) - so the control is withheld, not merely
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
# GET /watcher-section - no status yet: the fourth state (archiver#151)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_no_status_yet(client, session, bind_source):
    """Announced, but Watcher has never reported. Distinct from both
    `not_watching` and `watching` - #151's contract, unchanged by #142."""
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
# The cadence editor - new in archiver#158 (post-registration cadence was
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
    # "Delegate" stays reachable - it is the only way back to the consumer default.
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


# ---------------------------------------------------------------------------
# Panel layout - archiver#181
#
# The panel was one undifferentiated `.detail-grid` plus a trailing action
# strip. It is now a header (pause, top right), two authored `.detail-row`
# flex rows, and a block of one-per-row editable fields.
# ---------------------------------------------------------------------------


def _rows(html: str) -> tuple[str, str]:
    """The panel's two authored flex rows, split on their container class.

    ``str.split`` bounds each segment at the *next* marker, so segment 1 is
    exactly row one; row two is bounded by the editable-fields block that
    follows it.
    """
    segments = html.split('class="detail-row"')
    assert len(segments) == 3, f"expected exactly two .detail-row rows, found {len(segments) - 1}"
    return segments[1], segments[2].split('class="watch-panel__fields"')[0]


async def _watching(client, session, bind_source, slug: str, **item_kwargs):
    """A `watching` panel with every field populated.

    The revision matters: `last_changed_ago` is the one field derived from
    content rather than from the status frame, and without it the "Last changed
    is gone" assertion below would pass on an absent value rather than on a
    dropped one.
    """
    item = InfoItem(name=slug, **item_kwargs)
    session.add(item)
    await session.flush()
    src = await bind_source(session, item, slug=slug)
    session.add(
        SourceRevision(
            info_source_id=src.info_source_id,
            content_fingerprint="sha256:" + "b" * 64,
            captured_at=_STATUS_TS,
        )
    )
    _seed_status(session, item, applied_interval="6h")
    await session.flush()
    return await _section(client, item)


@pytest.mark.asyncio
async def test_row_one_is_health_cadence_next_due(client, session, bind_source):
    """Status at a glance: is it healthy, how often, and when next."""
    r = await _watching(client, session, bind_source, "row-one")
    assert r.status_code == 200
    row_one, _ = _rows(r.text)

    assert "Health" in row_one
    assert "Cadence" in row_one
    assert "Next due" in row_one
    # Provenance belongs to row two, not here.
    assert "Last attempted" not in row_one
    assert "Announcement" not in row_one


@pytest.mark.asyncio
async def test_row_two_is_provenance(client, session, bind_source):
    """When it last ran, when it last saw content, and where the generations stand."""
    r = await _watching(client, session, bind_source, "row-two")
    assert r.status_code == 200
    _, row_two = _rows(r.text)

    assert "Last attempted" in row_two
    assert "Last observed" in row_two
    assert "Announcement" in row_two
    assert "Health" not in row_two


@pytest.mark.asyncio
async def test_pause_sits_in_the_panel_header_above_both_rows(client, session, bind_source):
    """Pause moved out of the trailing action strip to the panel's top right.

    Asserted by document order rather than by geometry: the header precedes the
    first row, and the toggle is inside it.
    """
    r = await _watching(client, session, bind_source, "pause-header")
    assert r.status_code == 200
    html = r.text

    header_at = html.index("watch-panel__header")
    toggle_at = html.index("toggle-watch-active")
    first_row_at = html.index('class="detail-row"')
    assert header_at < toggle_at < first_row_at


@pytest.mark.asyncio
async def test_last_changed_leaves_the_panel(client, session, bind_source):
    """Dropped in #181: the six authored fields fill both rows, and Revision
    History on the same screen already carries every `captured_at`."""
    r = await _watching(client, session, bind_source, "no-last-changed")
    assert r.status_code == 200
    assert "Last changed" not in r.text


# ---------------------------------------------------------------------------
# The cadence editor as a view/edit row (the Domains pattern, #176)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cadence_row_renders_both_halves_with_row_level_controls(
    client, session, bind_source
):
    """View half: a readout plus Edit. Edit half: the select plus Cancel + Save."""
    r = await _watching(
        client,
        session,
        bind_source,
        "cadence-row",
        watch_spec={"schema_version": 1, "interval": "6h"},
    )
    assert r.status_code == 200
    html = r.text

    assert 'x-data="editableField"' in html
    assert "field-row__readout" in html
    assert ">Edit<" in html
    assert ">Cancel<" in html
    assert ">Save<" in html
    # The bare "Set" button the row replaces.
    assert ">Set<" not in html
    # Save still rides the unchanged POST contract.
    assert "watch-cadence" in html
    assert 'hx-swap="none"' in html


@pytest.mark.asyncio
async def test_cadence_readout_shows_the_announced_label_not_the_raw_interval(
    client, session, bind_source
):
    """The readout is the same vocabulary the select offers, not `6h`."""
    r = await _watching(
        client,
        session,
        bind_source,
        "cadence-readout",
        watch_spec={"schema_version": 1, "interval": "6h"},
    )
    assert r.status_code == 200
    readout = r.text.split('class="field-row__readout"')[1].split("</div>")[0]
    assert "Every 6 hours" in readout


@pytest.mark.asyncio
async def test_cadence_readout_names_the_delegate_choice(client, session, bind_source):
    """Delegating is a value an operator chose, so the readout must say so
    rather than render blank."""
    r = await _watching(
        client, session, bind_source, "cadence-delegate-readout", watch_spec={"schema_version": 1}
    )
    assert r.status_code == 200
    readout = r.text.split('class="field-row__readout"')[1].split("</div>")[0]
    assert "Consumer default" in readout


@pytest.mark.asyncio
async def test_cadence_row_hides_its_edit_half_before_alpine_runs(client, session, bind_source):
    """The `apiKeyRow` trade, not the `domainNotes` one.

    There is no no-JS save path to strand here: `watch-cadence` answers with a
    bare fragment rather than a 303, and the form only ever posted over HTMX. So
    the edit half carries the inline FOUC hint instead of rendering for a frame.
    """
    r = await _watching(client, session, bind_source, "cadence-fouc")
    assert r.status_code == 200
    edit_half = r.text.split('x-show="editing"')[1][:200]
    assert "display:none" in edit_half


# ---------------------------------------------------------------------------
# CR round 1 - the editor must be able to represent what it is editing
#
# `watch_spec.interval` accepts the whole `^[0-9]+[smhd]$` grammar through
# `PUT /api/v1/info-items/{id}/watch-spec`; the dashboard offers four values of
# it. An interval outside that subset is legitimate stored policy, and both
# halves of the row have to survive contact with one.
# ---------------------------------------------------------------------------

_OUT_OF_VOCABULARY = "30m"


def _readout(html: str) -> str:
    return html.split('class="field-row__readout"')[1].split("</div>")[0]


def _row_one_cadence(html: str) -> str:
    """The applied-cadence cell, which row one leads with."""
    row_one, _ = _rows(html)
    return row_one.split('">Cadence</span>')[1].split("</span>")[0]


@pytest.mark.asyncio
async def test_readout_and_row_one_agree_on_an_out_of_vocabulary_interval(
    client, session, bind_source
):
    """CR finding 1: one interval, one label.

    The readout used to build its own label from `CADENCE_LABELS`, which has no
    entry for `30m` and fell back to the raw string - so the same value rendered
    `~30 min` in row one and `30m` here. Both now read `format_interval`, the
    function that already owned this.
    """
    r = await _watching(
        client,
        session,
        bind_source,
        "cadence-oov-label",
        watch_spec={"schema_version": 1, "interval": _OUT_OF_VOCABULARY},
    )
    assert r.status_code == 200
    assert "~30 min" in _readout(r.text)
    assert "~30 min" in _row_one_cadence(r.text)
    assert "30m" not in _readout(r.text)


@pytest.mark.asyncio
async def test_the_select_carries_an_out_of_vocabulary_interval_as_its_selection(
    client, session, bind_source
):
    """CR finding 2: a control that cannot show its own value destroys it.

    With no matching option the browser selects index 0 - "Consumer default" -
    so Edit then Save, without touching anything, silently replaced a set policy
    with delegate and announced it.
    """
    r = await _watching(
        client,
        session,
        bind_source,
        "cadence-oov-option",
        watch_spec={"schema_version": 1, "interval": _OUT_OF_VOCABULARY},
    )
    assert r.status_code == 200
    assert '<option value="30m" selected>~30 min</option>' in r.text
    # Delegate must NOT be the selection: that is the clobber this guards.
    assert '<option value="" selected>' not in r.text


@pytest.mark.asyncio
async def test_an_unparseable_stored_interval_still_shows_itself(client, session, bind_source):
    """`format_interval` returns "" for a value outside the grammar, which the
    readout must not mistake for delegate. Only a hand-edited row reaches this -
    both write paths schema-validate - but the fallback is what keeps the row
    honest rather than quietly wrong."""
    r = await _watching(
        client,
        session,
        bind_source,
        "cadence-unparseable",
        watch_spec={"schema_version": 1, "interval": "banana"},
    )
    assert r.status_code == 200
    assert "banana" in _readout(r.text)
    assert "Consumer default" not in _readout(r.text)


@pytest.mark.asyncio
async def test_the_editable_row_says_which_cadence_it_edits(client, session, bind_source):
    """CR finding 3: row one is the *applied* cadence, this row the *announced*
    one. Both labelled "Cadence" left an operator no way to tell them apart -
    least of all under drift, when they disagree."""
    r = await _watching(client, session, bind_source, "cadence-labelled")
    assert r.status_code == 200
    assert "Announced cadence" in r.text
    # CR finding 6: a real <label for>, not aria-labelledby alone, so clicking
    # the word focuses the control.
    assert 'for="cadence-' in r.text


# ---------------------------------------------------------------------------
# POST /watch-cadence - the vocabulary guard
# ---------------------------------------------------------------------------


async def _seed_for_post(session, bind_source, slug: str, interval: str | None):
    spec: dict = {"schema_version": 1}
    if interval:
        spec["interval"] = interval
    item = InfoItem(name=slug, watch_spec=spec)
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug=slug)
    _seed_status(session, item)
    await session.flush()
    return item


@pytest.mark.asyncio
async def test_resaving_the_items_own_out_of_vocabulary_interval_is_a_no_op_not_a_refusal(
    client, session, bind_source
):
    """The guard exists to refuse a *hand-posted* value the dashboard never
    offered. Re-submitting what the item already announces is neither - and
    refusing it would strand the operator on any item the API configured."""
    item = await _seed_for_post(session, bind_source, "post-oov-own", _OUT_OF_VOCABULARY)

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/watch-cadence",
        headers=_HEADERS,
        data={"interval": _OUT_OF_VOCABULARY},
    )
    assert r.status_code == 200
    assert "showFlash" not in r.headers.get("HX-Trigger", "")

    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1, "interval": _OUT_OF_VOCABULARY}


@pytest.mark.asyncio
async def test_an_unoffered_interval_the_item_does_not_hold_is_still_refused(
    client, session, bind_source
):
    """Widening the guard must not open it: a value that is neither offered nor
    already announced is still a mistake, and the write must not land."""
    item = await _seed_for_post(session, bind_source, "post-oov-foreign", "6h")

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/watch-cadence",
        headers=_HEADERS,
        data={"interval": "45m"},
    )
    assert r.status_code == 200
    assert "showFlash" in r.headers.get("HX-Trigger", "")

    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1, "interval": "6h"}
