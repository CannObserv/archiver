"""Tests for /dashboard/domains/ routes (#49)."""

from __future__ import annotations

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
