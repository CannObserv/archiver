"""Tests for /dashboard/ home page (Epic 7)."""

from datetime import UTC, datetime

import pytest

from src.core.models import (
    InfoItem,
    InfoSource,
    SourceRevision,
)

_HEADERS = {"X-ExeDev-UserID": "ext-home", "X-ExeDev-Email": "home@example.com"}


def _make_source(url: str) -> InfoSource:
    return InfoSource(
        url=url,
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )


@pytest.mark.asyncio
async def test_home_unauthenticated_redirects(client):
    r = await client.get("/dashboard/", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_home_returns_200(client):
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_home_shows_entity_counts(client, session):
    session.add(InfoItem(name="Count Item"))
    src = _make_source("https://example.com/count-src")
    session.add(src)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    # counts appear in the page (at least a "1" from the item we added)
    assert "1" in r.text


@pytest.mark.asyncio
async def test_health_partial_returns_badge(client):
    r = await client.get("/dashboard/health", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "badge" in r.text
    assert "ok" in r.text


@pytest.mark.asyncio
async def test_health_partial_unauthenticated_redirects(client):
    r = await client.get("/dashboard/health", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_home_shows_recent_revisions(client, session):
    src = _make_source("https://example.com/recent-rev")
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "f" * 64,
        captured_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "2026-05-01" in r.text
    assert "Recent Changes" in r.text
    assert "Information Source" in r.text
    assert "Source Revision" in r.text
    assert "Observed" in r.text
    # source URL appears before fingerprint in column order
    url_pos = r.text.index("example.com/recent-rev")
    fp_pos = r.text.index("sha256:ffffffff")
    assert url_pos < fp_pos
