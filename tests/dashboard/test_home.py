"""Tests for /dashboard/ home page (Epic 7 + #49 redesign)."""

from datetime import UTC, datetime

import pytest

from src.core.models import (
    InfoItem,
    InfoItemSource,
    InfoSource,
    SourceRevision,
)
from src.core.models.domain import Domain

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
async def test_home_shows_register_cta(client):
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "Register Information Item" in r.text
    assert "/dashboard/register" in r.text


@pytest.mark.asyncio
async def test_home_shows_browse_info_items_link(client):
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "Browse Information Items" in r.text
    assert "/dashboard/info-items/" in r.text


@pytest.mark.asyncio
async def test_home_shows_entity_counts(client, session):
    session.add(InfoItem(name="Count Item"))
    src = _make_source("https://example.com/count-src")
    session.add(src)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
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
async def test_home_shows_recent_activity(client, session):
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
    assert "Recent Activity" in r.text
    assert "Item" in r.text
    assert "Source" in r.text
    assert "Revision" in r.text
    assert "Observed" in r.text
    url_pos = r.text.index("example.com/recent-rev")
    fp_pos = r.text.index("sha256:ffffffff")
    assert url_pos < fp_pos


@pytest.mark.asyncio
async def test_home_recent_activity_shows_item_name_when_bound(client, session):
    """When a revision is bound to an InfoItem, the Item column shows the item name."""
    src = _make_source("https://example.com/item-activity")
    item = InfoItem(name="Activity Item")
    session.add_all([src, item])
    await session.flush()
    binding = InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id)
    session.add(binding)
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime(2026, 5, 2, 10, 0, tzinfo=UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "Activity Item" in r.text


@pytest.mark.asyncio
async def test_home_domain_overview_appears_when_domains_exist(client, session):
    """Domain overview table renders when domains + sources exist."""
    domain = Domain(name="overview.example.com")
    session.add(domain)
    await session.flush()
    src = InfoSource(
        url="https://overview.example.com/path",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
        domain_name="overview.example.com",
    )
    session.add(src)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "overview.example.com" in r.text
    assert "Domains" in r.text
