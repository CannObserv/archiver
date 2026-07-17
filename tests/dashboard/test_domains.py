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
async def test_domain_detail_archived_shows_restore_in_danger_zone(client, session):
    """Archived domain: Restore action lives in the danger-zone block (#82)."""
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
    assert "danger-zone" in r.text
    assert "/dashboard/domains/dz-archived.example.com/restore" in r.text


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
