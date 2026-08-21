"""Tests for /dashboard/domains/ routes (#49)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.core.models.domain import Domain

_HEADERS = {"X-ExeDev-UserID": "ext-dom", "X-ExeDev-Email": "dom@example.com"}


def _make_domain(name: str, **kwargs) -> Domain:
    return Domain(name=name, **kwargs)


def _make_source(url: str, domain_name: str) -> InfoSource:
    return InfoSource(
        url=url,
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
        domain_name=domain_name,
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_list_200(client):
    r = await client.get("/dashboard/domains/", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_domain_list_unauthenticated_redirects(client):
    r = await client.get("/dashboard/domains/", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_domain_list_shows_domains(client, session):
    domain = _make_domain("list-check.example.com")
    session.add(domain)
    await session.flush()

    r = await client.get("/dashboard/domains/", headers=_HEADERS)
    assert r.status_code == 200
    assert "list-check.example.com" in r.text


@pytest.mark.asyncio
async def test_domain_list_shows_source_count(client, session):
    domain = _make_domain("src-count.example.com")
    session.add(domain)
    await session.flush()
    src = _make_source("https://src-count.example.com/a", "src-count.example.com")
    session.add(src)
    await session.flush()

    r = await client.get("/dashboard/domains/", headers=_HEADERS)
    assert r.status_code == 200
    assert "src-count.example.com" in r.text


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_detail_200(client, session):
    domain = _make_domain("detail.example.com")
    session.add(domain)
    await session.flush()

    r = await client.get("/dashboard/domains/detail.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "detail.example.com" in r.text


@pytest.mark.asyncio
async def test_domain_detail_404_when_absent(client):
    r = await client.get("/dashboard/domains/no-such.example.com", headers=_HEADERS)
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_domain_detail_shows_linked_sources(client, session):
    domain = _make_domain("linked.example.com")
    session.add(domain)
    await session.flush()
    src = _make_source("https://linked.example.com/page", "linked.example.com")
    session.add(src)
    await session.flush()

    r = await client.get("/dashboard/domains/linked.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "https://linked.example.com/page" in r.text
    # External-open affordance is a shared "Open ↗" button (modeled on Copy).
    assert 'href="https://linked.example.com/page"' in r.text
    assert ">Open ↗</a>" in r.text


@pytest.mark.asyncio
async def test_domain_detail_shows_source_count_in_heading(client, session):
    """Related-collection tables carry the row count in the <h2> (#82, docs/SCREENS.md)."""
    session.add(_make_domain("count-head.example.com"))
    await session.flush()
    for i in range(3):
        session.add(_make_source(f"https://count-head.example.com/{i}", "count-head.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/count-head.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "Information Sources (3)" in r.text


@pytest.mark.asyncio
async def test_domain_detail_source_count_is_total_not_page(client, session):
    """Count is a route COUNT over all rows, not the current page's length (#82)."""
    session.add(_make_domain("count-page.example.com"))
    await session.flush()
    for i in range(3):
        session.add(_make_source(f"https://count-page.example.com/{i}", "count-page.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/count-page.example.com?limit=2", headers=_HEADERS)
    assert r.status_code == 200
    # Page shows 2 rows but the heading must report the full total.
    assert "Information Sources (3)" in r.text


@pytest.mark.asyncio
async def test_domain_detail_source_count_zero(client, session):
    """Empty state still reports a count (#82)."""
    session.add(_make_domain("count-zero.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/count-zero.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "Information Sources (0)" in r.text


@pytest.mark.asyncio
async def test_domain_detail_offset_past_end_no_contradiction(client, session):
    """Overshot offset: the empty state must not claim the domain has no sources
    while the heading reports a nonzero count (CR round 7, finding 1)."""
    session.add(_make_domain("count-over.example.com"))
    await session.flush()
    for i in range(3):
        session.add(_make_source(f"https://count-over.example.com/{i}", "count-over.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/count-over.example.com?offset=999", headers=_HEADERS)
    assert r.status_code == 200
    assert "Information Sources (3)" in r.text
    # The "none registered" copy is reserved for a genuinely empty collection.
    assert "No Information Sources registered for this domain yet" not in r.text
    assert "No sources on this page" in r.text
    # Offers a way back to a populated page. Since #176 the link carries both
    # tables' windows and resets only the source offset; `&` autoescapes.
    assert "item_offset=0&amp;offset=0" in r.text


@pytest.mark.asyncio
async def test_domain_detail_empty_collection_keeps_registered_copy(client, session):
    """A genuinely empty collection keeps the original empty-state wording."""
    session.add(_make_domain("count-none.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/count-none.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "No Information Sources registered for this domain yet" in r.text
    assert "No sources on this page" not in r.text


@pytest.mark.asyncio
async def test_domain_detail_pagination_next_prev(client, session):
    """Pagination nav reflects position: page 1 of 3 offers Next, the last page
    offers only Previous. `has_more` comes from the limit+1 probe, kept separate
    from the heading COUNT so it stays snapshot-consistent (CR round 8)."""
    session.add(_make_domain("pager.example.com"))
    await session.flush()
    for i in range(3):
        session.add(_make_source(f"https://pager.example.com/{i}", "pager.example.com"))
    await session.flush()

    first = await client.get("/dashboard/domains/pager.example.com?limit=2", headers=_HEADERS)
    assert first.status_code == 200
    assert "Next →" in first.text
    assert "← Previous" not in first.text

    last = await client.get(
        "/dashboard/domains/pager.example.com?limit=2&offset=2", headers=_HEADERS
    )
    assert last.status_code == 200
    assert "Next →" not in last.text
    assert "← Previous" in last.text


@pytest.mark.asyncio
async def test_domain_detail_uses_entity_card_eyebrow(client, session):
    """Domain detail converges on the entity-card + eyebrow header (#82)."""
    session.add(_make_domain("card.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/card.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert 'class="eyebrow">Domain<' in r.text
    assert "entity-card__header" in r.text
    # Header action slot is gone — Archive/Restore moved to the danger zone.
    assert "entity-section__header" not in r.text


@pytest.mark.asyncio
async def test_domain_detail_archive_in_danger_zone(client, session):
    """Active domain: Archive action lives in a danger-zone block (#82)."""
    session.add(_make_domain("dz-active.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/dz-active.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "danger-zone" in r.text
    assert "/dashboard/domains/dz-active.example.com/archive" in r.text


@pytest.mark.asyncio
async def test_domain_archive_confirm_is_static(client, session):
    """The Archive confirm message is static — the domain name is not spliced
    into the onclick JS (names are unvalidated; avoid injection) (#78 CR8)."""
    # A crafted name with a quote would break an interpolated confirm() string.
    session.add(_make_domain("ev'il.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/ev'il.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "confirm('Archive this domain?')" in r.text
    assert "Archive ev'il.example.com?" not in r.text


@pytest.mark.asyncio
async def test_domain_detail_archived_hoists_restore_out_of_danger_zone(client, session):
    """Archived domain: Restore is hoisted next to the Status badge in the header,
    and the danger zone (Archive-only) is hidden — nothing destructive remains (#82)."""
    session.add(
        _make_domain(
            "dz-archived.example.com",
            is_active=False,
            archived_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
    )
    await session.flush()

    r = await client.get("/dashboard/domains/dz-archived.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "/dashboard/domains/dz-archived.example.com/restore" in r.text
    # Restore lives up top now, not in a danger zone; the zone is archive-only.
    assert "danger-zone" not in r.text
    assert "/dashboard/domains/dz-archived.example.com/archive" not in r.text


# ---------------------------------------------------------------------------
# Archive / restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_domain_via_dashboard(client, session):
    domain = _make_domain("arch-dash.example.com")
    session.add(domain)
    await session.flush()

    r = await client.post("/dashboard/domains/arch-dash.example.com/archive", headers=_HEADERS)
    # Expect redirect to detail or 200 partial
    assert r.status_code in (200, 303)


@pytest.mark.asyncio
async def test_restore_domain_via_dashboard(client, session):
    domain = _make_domain("restore-dash.example.com", archived_at=datetime.now(UTC))
    session.add(domain)
    await session.flush()

    r = await client.post("/dashboard/domains/restore-dash.example.com/restore", headers=_HEADERS)
    assert r.status_code in (200, 303)


# ---------------------------------------------------------------------------
# Inline notes edit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_notes_returns_200_or_redirect(client, session):
    domain = _make_domain("notes-dash.example.com")
    session.add(domain)
    await session.flush()

    r = await client.post(
        "/dashboard/domains/notes-dash.example.com/notes",
        headers=_HEADERS,
        data={"notes": "my notes"},
    )
    assert r.status_code in (200, 303)


# ---------------------------------------------------------------------------
# Header panel — Open button + notes (#176)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_detail_header_has_open_button(client, session):
    """Domain has no URL column — the affordance targets https://{name} (#176)."""
    session.add(_make_domain("open-btn.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/open-btn.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert 'href="https://open-btn.example.com"' in r.text
    assert ">Open ↗</a>" in r.text


@pytest.mark.asyncio
async def test_domain_detail_notes_live_inside_header_card(client, session):
    """Notes is a row of the header .entity-card, not a sibling block below it (#176)."""
    session.add(_make_domain("notes-in-panel.example.com", notes="operator note"))
    await session.flush()

    r = await client.get("/dashboard/domains/notes-in-panel.example.com", headers=_HEADERS)
    assert r.status_code == 200
    head = r.text.index('class="entity-card"')
    notes = r.text.index('id="notes-section"')
    sources = r.text.index("Information Sources (")
    assert head < notes < sources


@pytest.mark.asyncio
async def test_domain_detail_notes_render_read_only_with_edit_button(client, session):
    """View mode: bordered read-only content + an Edit button; no bare textarea (#176)."""
    session.add(_make_domain("notes-ro.example.com", notes="read me"))
    await session.flush()

    r = await client.get("/dashboard/domains/notes-ro.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert 'x-data="domainNotes"' in r.text
    assert 'class="notes-readout"' in r.text
    # Heading carries its own class, not a borrowed .detail-grid__label.
    assert 'class="notes-heading"' in r.text
    assert "read me" in r.text
    # View mode hides on edit; edit mode hides on view — both are x-show driven.
    assert 'x-show="!editing"' in r.text
    assert 'x-show="editing"' in r.text
    assert '@click="editing = true"' in r.text


@pytest.mark.asyncio
async def test_domain_detail_notes_edit_mode_has_cancel_and_save(client, session):
    session.add(_make_domain("notes-actions.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/notes-actions.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert 'x-ref="notesBox"' in r.text
    assert ">Cancel</button>" in r.text
    assert ">Save</button>" in r.text


@pytest.mark.asyncio
async def test_domain_detail_notes_empty_state(client, session):
    """A domain with no notes still shows the read-only region, with placeholder copy."""
    session.add(_make_domain("notes-empty.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/notes-empty.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "No notes yet." in r.text


@pytest.mark.asyncio
async def test_update_notes_partial_returns_view_mode(client, session):
    """The HTMX swap returns the same read-only-first partial, not a bare form (#176)."""
    session.add(_make_domain("notes-swap.example.com"))
    await session.flush()

    r = await client.post(
        "/dashboard/domains/notes-swap.example.com/notes",
        headers={**_HEADERS, "HX-Request": "true"},
        data={"notes": "swapped in"},
    )
    assert r.status_code == 200
    assert 'x-data="domainNotes"' in r.text
    assert "swapped in" in r.text
    # Focus-move script is emitted on the swap only (docs/SCREENS.md).
    assert 'getElementById("domain-notes-heading")' in r.text


@pytest.mark.asyncio
async def test_update_notes_htmx_carries_success_toast(client, session):
    """SCREENS.md HTMX mutations: the swap also fires a showFlash toast."""
    session.add(_make_domain("notes-toast.example.com"))
    await session.flush()

    r = await client.post(
        "/dashboard/domains/notes-toast.example.com/notes",
        headers={**_HEADERS, "HX-Request": "true"},
        data={"notes": "toasted"},
    )
    assert r.status_code == 200
    assert "showFlash" in r.headers["HX-Trigger"]


@pytest.mark.asyncio
async def test_update_notes_without_htmx_redirects(client, session):
    """No-JS submit must land on the detail page, not on a bare fragment."""
    session.add(_make_domain("notes-nojs.example.com"))
    await session.flush()

    r = await client.post(
        "/dashboard/domains/notes-nojs.example.com/notes",
        headers=_HEADERS,
        data={"notes": "saved without js"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard/domains/notes-nojs.example.com"

    detail = await client.get("/dashboard/domains/notes-nojs.example.com", headers=_HEADERS)
    assert "saved without js" in detail.text


@pytest.mark.asyncio
async def test_domain_detail_notes_edit_form_is_reachable_without_alpine(client, session):
    """The edit form must not be hidden by inline CSS.

    `x-show` alone leaves it visible when Alpine never runs, which is what makes
    the method/action POST fallback reachable (docs/SCREENS.md). An
    inline `display:none` would strand it — the fallback would be present in the
    markup and unusable, which is worse than not claiming one.
    """
    session.add(_make_domain("notes-nojs-form.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/notes-nojs-form.example.com", headers=_HEADERS)
    assert r.status_code == 200
    form_start = r.text.index('x-show="editing"')
    form_tag = r.text[form_start : r.text.index(">", form_start)]
    assert "display:none" not in form_tag.replace(" ", "")
    # And the fallback it protects is actually declared.
    assert 'action="/dashboard/domains/notes-nojs-form.example.com/notes"' in r.text


@pytest.mark.asyncio
async def test_domain_detail_notes_omits_focus_script_on_full_page(client, session):
    """The focus move belongs to the swap response, not the initial render."""
    session.add(_make_domain("notes-nofocus.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/notes-nofocus.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert 'getElementById("domain-notes-heading")' not in r.text


# ---------------------------------------------------------------------------
# Information Items section (#176)
# ---------------------------------------------------------------------------


def _make_item(name: str) -> InfoItem:
    return InfoItem(name=name)


def _bind(item: InfoItem, src: InfoSource) -> InfoItemSource:
    return InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id)


async def _domain_with_items(session, host: str, count: int) -> None:
    session.add(_make_domain(host))
    await session.flush()
    for i in range(count):
        src = _make_source(f"https://{host}/{i}", host)
        item = _make_item(f"{host} item {i}")
        session.add_all([src, item])
        await session.flush()
        session.add(_bind(item, src))
    await session.flush()


@pytest.mark.asyncio
async def test_domain_detail_lists_information_items(client, session):
    await _domain_with_items(session, "items-list.example.com", 2)

    r = await client.get("/dashboard/domains/items-list.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "items-list.example.com item 0" in r.text
    assert "items-list.example.com item 1" in r.text


@pytest.mark.asyncio
async def test_domain_detail_items_section_sits_between_header_and_sources(client, session):
    await _domain_with_items(session, "items-order.example.com", 1)

    r = await client.get("/dashboard/domains/items-order.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert r.text.index("Information Items (") < r.text.index("Information Sources (")


@pytest.mark.asyncio
async def test_domain_detail_item_count_is_total_not_page(client, session):
    """Heading count is a route COUNT over all rows, not the page's length.

    docs/SCREENS.md § Related-collection tables.
    """
    await _domain_with_items(session, "items-count.example.com", 3)

    r = await client.get(
        "/dashboard/domains/items-count.example.com?item_limit=2", headers=_HEADERS
    )
    assert r.status_code == 200
    assert "Information Items (3)" in r.text


@pytest.mark.asyncio
async def test_domain_detail_items_exclude_deactivated_bindings(client, session):
    """Only the active binding counts — a superseded primary is succession history."""
    session.add(_make_domain("items-deact.example.com"))
    await session.flush()
    src = _make_source("https://items-deact.example.com/a", "items-deact.example.com")
    item = _make_item("retired binding item")
    session.add_all([src, item])
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
            deactivated_at=datetime.now(UTC),
        )
    )
    await session.flush()

    r = await client.get("/dashboard/domains/items-deact.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "Information Items (0)" in r.text
    assert "retired binding item" not in r.text


@pytest.mark.asyncio
async def test_domain_detail_items_empty_state(client, session):
    session.add(_make_domain("items-none.example.com"))
    await session.flush()

    r = await client.get("/dashboard/domains/items-none.example.com", headers=_HEADERS)
    assert r.status_code == 200
    assert "No Information Items bound to this domain yet." in r.text


@pytest.mark.asyncio
async def test_domain_detail_items_overshot_offset_no_contradiction(client, session):
    """Overshot item_offset gets its own empty state, not the "none bound" copy."""
    await _domain_with_items(session, "items-overshoot.example.com", 2)

    r = await client.get(
        "/dashboard/domains/items-overshoot.example.com?item_offset=50", headers=_HEADERS
    )
    assert r.status_code == 200
    # The heading still reports the full total — that is what keeps the
    # "no items on this page" copy from contradicting it.
    assert "Information Items (2)" in r.text
    assert "No items on this page" in r.text
    assert "No Information Items bound to this domain yet." not in r.text


@pytest.mark.asyncio
async def test_domain_detail_items_pagination_is_independent_of_sources(client, session):
    """Two paginated tables on one page must not fight over limit/offset (#176)."""
    await _domain_with_items(session, "items-indep.example.com", 3)

    r = await client.get(
        "/dashboard/domains/items-indep.example.com?item_limit=1&limit=1", headers=_HEADERS
    )
    assert r.status_code == 200
    # Each Next link carries both windows so following one preserves the other:
    # the Items link pins the source offset, the Sources link pins the item one.
    assert "offset=0&amp;item_limit=1&amp;item_offset=1" in r.text
    assert "item_offset=0&amp;offset=1" in r.text


@pytest.mark.asyncio
async def test_domain_detail_item_pagination_params_clamp(client, session):
    """item_limit/item_offset clamp like limit/offset — no 422 on a hand-edited URL."""
    await _domain_with_items(session, "items-clamp.example.com", 1)

    r = await client.get(
        "/dashboard/domains/items-clamp.example.com?item_limit=abc&item_offset=-9",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "items-clamp.example.com item 0" in r.text
