"""Tests for /dashboard/info-sources/ routes."""

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


def _root_doc(url: str) -> dict:
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


def _fragment_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "h1"},
        "fingerprint": {},
    }


def _make_root(url: str = "https://example.com/page") -> InfoSource:
    return InfoSource(source_spec=_root_doc(url), schema_version=1)


def _make_fragment(parent: InfoSource) -> InfoSource:
    return InfoSource(
        source_spec=_fragment_doc(),
        schema_version=1,
        parent_info_source_id=parent.info_source_id,
    )


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
async def test_list_shows_root_url(client, session):
    src = _make_root("https://example.com/list-test")
    session.add(src)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "https://example.com/list-test" in r.text


@pytest.mark.asyncio
async def test_list_shape_filter_root(client, session):
    root = _make_root("https://example.com/root-only")
    session.add(root)
    await session.flush()
    fragment = _make_fragment(root)
    session.add(fragment)
    await session.flush()

    r = await client.get(_LIST_URL + "?shape=root", headers=_HEADERS)
    assert r.status_code == 200
    assert "https://example.com/root-only" in r.text
    # Fragment has no URL; its ID should not appear in the root-filtered view
    assert str(fragment.info_source_id) not in r.text


@pytest.mark.asyncio
async def test_list_shape_filter_fragment(client, session):
    root = _make_root("https://example.com/parent-for-filter")
    session.add(root)
    await session.flush()
    fragment = _make_fragment(root)
    session.add(fragment)
    await session.flush()

    r = await client.get(_LIST_URL + "?shape=fragment", headers=_HEADERS)
    assert r.status_code == 200
    assert str(fragment.info_source_id) in r.text


@pytest.mark.asyncio
async def test_list_url_search(client, session):
    session.add(_make_root("https://example.com/needle-in-url"))
    session.add(_make_root("https://example.com/unrelated"))
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
    src = _make_root("https://example.com/detail-unauth")
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
async def test_detail_shows_source_spec(client, session):
    src = _make_root("https://example.com/spec-display")
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "https://example.com/spec-display" in r.text


@pytest.mark.asyncio
async def test_detail_fragment_shows_parent_link(client, session):
    root = _make_root("https://example.com/parent-of-fragment")
    session.add(root)
    await session.flush()
    fragment = _make_fragment(root)
    session.add(fragment)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{fragment.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert str(root.info_source_id) in r.text


@pytest.mark.asyncio
async def test_detail_shows_bound_items(client, session):
    src = _make_root("https://example.com/bound-item-test")
    session.add(src)
    await session.flush()
    item = InfoItem(name="Bound Item Name")
    session.add(item)
    await session.flush()
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=src.info_source_id,
        role=None,
    )
    session.add(binding)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Bound Item Name" in r.text


@pytest.mark.asyncio
async def test_detail_shows_revisions(client, session):
    src = _make_root("https://example.com/revisions-test")
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
    assert "source_spec" in r.text


# ---------------------------------------------------------------------------
# POST /dashboard/info-sources/new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_unauthenticated_redirects(client):
    r = await client.post(_NEW_URL, data={"source_spec": "{}"}, follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_create_valid_root_redirects_to_detail(client, session):
    spec = _root_doc("https://example.com/create-via-dashboard")
    import json

    r = await client.post(
        _NEW_URL,
        data={"source_spec": json.dumps(spec)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "/dashboard/info-sources/" in r.headers["location"]


@pytest.mark.asyncio
async def test_create_invalid_spec_rerenders_form_with_error(client):
    r = await client.post(
        _NEW_URL,
        data={"source_spec": "not-json"},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "invalid" in r.text.lower() or "error" in r.text.lower()
    assert "not-json" in r.text  # source_spec_raw round-trips into server response


@pytest.mark.asyncio
async def test_create_duplicate_url_rerenders_form_with_conflict_message(client, session):
    import json

    spec = _root_doc("https://example.com/duplicate-dashboard")
    existing = _make_root("https://example.com/duplicate-dashboard")
    session.add(existing)
    await session.flush()

    r = await client.post(
        _NEW_URL,
        data={"source_spec": json.dumps(spec)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert str(existing.info_source_id) in r.text
