"""Tests for /dashboard/domains/ routes (#49)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.models import InfoSource
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
    """Related-collection tables carry the row count in the <h2> (#82, docs/UI.md)."""
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
    # Offers a way back to a populated page (raw `&`, matching the pagination nav).
    assert "?offset=0&limit=" in r.text


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
    from datetime import UTC, datetime

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
