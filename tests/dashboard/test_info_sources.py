"""Tests for /dashboard/info-sources/ routes."""

import json
from datetime import UTC, datetime

import pytest

from src.core.models import (
    InfoItem,
    InfoItemSource,
    InfoSource,
    SourceRevision,
)

_HEADERS = {"X-ExeDev-UserID": "ext-sources", "X-ExeDev-Email": "sources@example.com"}
_LIST_URL = "/dashboard/info-sources/"
_NEW_URL = "/dashboard/info-sources/new"


def _spec(algorithm: str = "full_page") -> dict:
    doc: dict = {
        "schema_version": 1,
        "extraction": {"algorithm": algorithm},
        "fingerprint": {},
    }
    if algorithm != "full_page":
        doc["extraction"]["selector"] = "#x"
    return doc


def _make_source(url: str = "https://example.com/page") -> InfoSource:
    return InfoSource(url=url, source_specs=[_spec()])


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_unauthenticated_redirects(client):
    r = await client.get(_LIST_URL, follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_list_empty_returns_200(client):
    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_list_shows_url(client, session):
    src = _make_source("https://example.com/list-test")
    session.add(src)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "https://example.com/list-test" in r.text


@pytest.mark.asyncio
async def test_list_url_search(client, session):
    session.add(_make_source("https://example.com/needle-in-url"))
    session.add(_make_source("https://example.com/unrelated"))
    await session.flush()

    r = await client.get(_LIST_URL + "?url_contains=needle", headers=_HEADERS)
    assert r.status_code == 200
    assert "needle" in r.text
    assert "unrelated" not in r.text


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_unauthenticated_redirects(client, session):
    src = _make_source("https://example.com/detail-unauth")
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_detail_not_found_returns_404(client):
    from ulid import ULID

    r = await client.get(f"/dashboard/info-sources/{ULID()}", headers=_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_detail_shows_url(client, session):
    src = _make_source("https://example.com/spec-display")
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "https://example.com/spec-display" in r.text


@pytest.mark.asyncio
async def test_detail_shows_bound_items(client, session):
    src = _make_source("https://example.com/bound-item-test")
    session.add(src)
    await session.flush()
    item = InfoItem(name="Bound Item Name")
    session.add(item)
    await session.flush()
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=src.info_source_id,
    )
    session.add(binding)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Bound Item Name" in r.text


@pytest.mark.asyncio
async def test_detail_shows_revisions(client, session):
    src = _make_source("https://example.com/revisions-test")
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "2026-01-15" in r.text


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_unauthenticated_redirects(client):
    r = await client.get(_NEW_URL, follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_new_returns_form(client):
    r = await client.get(_NEW_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


# ---------------------------------------------------------------------------
# POST /dashboard/info-sources/new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_unauthenticated_redirects(client):
    r = await client.post(
        _NEW_URL, data={"url": "https://example.com", "source_specs": "[]"}, follow_redirects=False
    )
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_create_valid_redirects_to_detail(client, session):
    specs = json.dumps([_spec()])
    r = await client.post(
        _NEW_URL,
        data={"url": "https://example.com/create-via-dashboard", "source_specs": specs},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "/dashboard/info-sources/" in r.headers["location"]


@pytest.mark.asyncio
async def test_create_missing_url_rerenders_form_with_error(client):
    r = await client.post(
        _NEW_URL,
        data={"url": "", "source_specs": "[]"},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_create_invalid_specs_rerenders_form_with_error(client):
    r = await client.post(
        _NEW_URL,
        data={"url": "https://example.com", "source_specs": "not-json"},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "not-json" in r.text
