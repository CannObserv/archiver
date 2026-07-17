"""Tests for /dashboard/source-revisions/ routes."""

from datetime import UTC, datetime

import pytest

from src.core.models import (
    InfoItem,
    InfoItemSourceRevision,
    InfoSource,
    SourceRevision,
)

_HEADERS = {"X-ExeDev-UserID": "ext-revisions", "X-ExeDev-Email": "revisions@example.com"}
_LIST_URL = "/dashboard/source-revisions/"


def _make_source(url: str = "https://example.com/rev-test") -> InfoSource:
    return InfoSource(
        url=url,
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )


def _make_revision(source: InfoSource, fp_suffix: str = "a" * 64) -> SourceRevision:
    return SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint=f"sha256:{fp_suffix}",
        captured_at=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# GET /dashboard/source-revisions/
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
async def test_list_shows_fingerprint(client, session):
    src = _make_source("https://example.com/fp-show")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "b" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "bbbbbbbb" in r.text


@pytest.mark.asyncio
async def test_list_filter_by_info_source_id(client, session):
    src_a = _make_source("https://example.com/src-filter-a")
    src_b = _make_source("https://example.com/src-filter-b")
    session.add(src_a)
    session.add(src_b)
    await session.flush()
    rev_a = _make_revision(src_a, "a" * 64)
    rev_b = _make_revision(src_b, "c" * 64)
    session.add(rev_a)
    session.add(rev_b)
    await session.flush()

    r = await client.get(_LIST_URL + f"?info_source_id={src_a.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "aaaaaaaa" in r.text
    assert "cccccccc" not in r.text


# ---------------------------------------------------------------------------
# GET /dashboard/source-revisions/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_unauthenticated_redirects(client, session):
    src = _make_source("https://example.com/rev-detail-unauth")
    session.add(src)
    await session.flush()
    rev = _make_revision(src)
    session.add(rev)
    await session.flush()

    r = await client.get(
        f"/dashboard/source-revisions/{rev.source_revision_id}", follow_redirects=False
    )
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_detail_not_found_returns_404(client):
    from ulid import ULID

    r = await client.get(f"/dashboard/source-revisions/{ULID()}", headers=_HEADERS)
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_detail_shows_fingerprint(client, session):
    src = _make_source("https://example.com/rev-fp-detail")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "d" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "dddddddd" in r.text


@pytest.mark.asyncio
async def test_detail_shows_source_link(client, session):
    src = _make_source("https://example.com/rev-source-link")
    session.add(src)
    await session.flush()
    rev = _make_revision(src)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert str(src.info_source_id) in r.text


@pytest.mark.asyncio
async def test_detail_shows_bound_items(client, session):
    src = _make_source("https://example.com/rev-bound-items")
    session.add(src)
    await session.flush()
    rev = _make_revision(src)
    session.add(rev)
    await session.flush()

    item = InfoItem(name="Rev-Bound Item")
    session.add(item)
    await session.flush()

    iisr = InfoItemSourceRevision(
        info_item_id=item.info_item_id,
        source_revision_id=rev.source_revision_id,
        bound_at=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
    )
    session.add(iisr)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Rev-Bound Item" in r.text


@pytest.mark.asyncio
async def test_detail_bound_item_current_pin_badge(client, session):
    """This revision is the item's latest binding → 'current pin' (#78 #9)."""
    src = _make_source("https://example.com/rev-pin-a")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "7" * 64)
    session.add(rev)
    await session.flush()

    item = InfoItem(name="Current-Pin Item")
    session.add(item)
    await session.flush()
    session.add(
        InfoItemSourceRevision(
            info_item_id=item.info_item_id,
            source_revision_id=rev.source_revision_id,
            bound_at=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
        )
    )
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert ">current pin<" in r.text
    assert ">superseded<" not in r.text


@pytest.mark.asyncio
async def test_detail_bound_item_superseded_badge(client, session):
    """Item later bound to a newer revision → this one is 'superseded' (#78 #9)."""
    src = _make_source("https://example.com/rev-older")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "8" * 64)
    rev_newer = _make_revision(src, "9" * 64)
    session.add(rev)
    session.add(rev_newer)
    await session.flush()

    item = InfoItem(name="Older-Binding Item")
    session.add(item)
    await session.flush()
    session.add(
        InfoItemSourceRevision(
            info_item_id=item.info_item_id,
            source_revision_id=rev.source_revision_id,
            bound_at=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
        )
    )
    session.add(
        InfoItemSourceRevision(
            info_item_id=item.info_item_id,
            source_revision_id=rev_newer.source_revision_id,
            bound_at=datetime(2026, 3, 11, 9, 0, tzinfo=UTC),
        )
    )
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert ">superseded<" in r.text
    assert ">current pin<" not in r.text


@pytest.mark.asyncio
async def test_detail_header_eyebrow_replaces_breadcrumb(client, session):
    """Header shows a singular 'Information Source Revision' eyebrow, not a
    breadcrumb, and drops the truncated fingerprint (full one lives in the grid)."""
    src = _make_source("https://example.com/rev-eyebrow")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "d" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'class="eyebrow"' in r.text
    assert "Information Source Revision</p>" in r.text
    assert 'aria-label="Breadcrumb"' not in r.text
    # Truncated fingerprint removed from the header; full one remains below.
    assert ("d" * 24 + "…") not in r.text
    assert "d" * 64 in r.text


@pytest.mark.asyncio
async def test_detail_info_source_has_external_link(client, session):
    """The Information Source value carries an external ↗ link to the target URL."""
    src = _make_source("https://example.com/rev-extlink")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "e" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'href="https://example.com/rev-extlink"' in r.text
    assert 'target="_blank"' in r.text
    # Modeled on the Copy affordance — an "Open ↗" button, not a bare icon link.
    assert "btn btn--secondary btn--sm" in r.text
    assert ">Open ↗</a>" in r.text


@pytest.mark.asyncio
async def test_detail_wide_items_span_full_width(client, session):
    """Fingerprint + Information Source get full-width grid cells so long values
    extend horizontally at wide viewports."""
    src = _make_source("https://example.com/rev-wide")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "c" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert r.text.count("detail-grid__item--full") == 2


@pytest.mark.asyncio
async def test_detail_uses_detail_grid_item_markup(client, session):
    """Normalize to the InfoItem detail grid convention (#78): grid __item
    wrappers, not bare <dl><dt><dd> which misaligns against .detail-grid CSS."""
    src = _make_source("https://example.com/rev-grid")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "1" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "detail-grid__item" in r.text
    assert "<dt>" not in r.text


@pytest.mark.asyncio
async def test_detail_bound_timestamp_labeled_utc(client, session):
    """Bound Items timestamp carries a UTC suffix like the rest of the screen (#78)."""
    src = _make_source("https://example.com/rev-utc")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "2" * 64)
    session.add(rev)
    await session.flush()

    item = InfoItem(name="UTC-Label Item")
    session.add(item)
    await session.flush()

    session.add(
        InfoItemSourceRevision(
            info_item_id=item.info_item_id,
            source_revision_id=rev.source_revision_id,
            bound_at=datetime(2026, 3, 10, 11, 30, tzinfo=UTC),
        )
    )
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "11:30 UTC" in r.text


@pytest.mark.asyncio
async def test_detail_has_sibling_revisions_link(client, session):
    """Detail links to all revisions for the same source (#78)."""
    src = _make_source("https://example.com/rev-sibling")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "3" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert f"/dashboard/source-revisions/?info_source_id={src.info_source_id}" in r.text


@pytest.mark.asyncio
async def test_detail_has_copy_affordance(client, session):
    """Fingerprint / revision id are copyable via the shared Alpine idiom (#78)."""
    src = _make_source("https://example.com/rev-copy")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "4" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "navigator.clipboard" in r.text


@pytest.mark.asyncio
async def test_detail_http_cache_uri_is_linked(client, session):
    """An http(s) cache URI renders as an openable link (#78)."""
    src = _make_source("https://example.com/rev-http-cache")
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "5" * 64,
        captured_at=datetime(2026, 3, 1, tzinfo=UTC),
        content_cache_uri="https://cache.example.com/blob/xyz",
    )
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'href="https://cache.example.com/blob/xyz"' in r.text
    # http(s) cache URI opens via the shared "Open ↗" button affordance.
    assert ">Open ↗</a>" in r.text


@pytest.mark.asyncio
async def test_copyable_binds_cache_uri_as_data_no_js_breakout(client, session):
    """A crafted cache URI cannot break out of the copy handler's JS context (#78 CR1).

    The value is bound via ``|tojson`` and copied through a reactive property, so a
    single quote is escaped (``\\u0027``) rather than spliced raw into ``writeText('…')``.
    """
    src = _make_source("https://example.com/rev-copy-escape")
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime(2026, 3, 1, tzinfo=UTC),
        content_cache_uri="gs://bucket/x'quote",
    )
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    # Copied via the reactive property, never spliced into JS source.
    assert "writeText(v)" in r.text
    assert "writeText('" not in r.text
    # The single quote is escaped in the bound data, and the raw form never appears.
    assert "x'quote" not in r.text
    assert "x\\u0027quote" in r.text


@pytest.mark.asyncio
async def test_detail_full_page_does_not_steal_focus(client, session):
    """Full-page render exposes a focusable heading but does not auto-focus it (#78 CR3)."""
    src = _make_source("https://example.com/rev-focus")
    session.add(src)
    await session.flush()
    rev = _make_revision(src, "b" * 64)
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'id="revision-heading"' in r.text
    # No focus-move script on a plain page load — only after an HTMX swap.
    assert 'getElementById("revision-heading")' not in r.text


@pytest.mark.asyncio
async def test_detail_nonhttp_cache_uri_shown_not_linked(client, session):
    """A gs:// cache URI is shown (copyable) but not wrapped in an href (#78)."""
    src = _make_source("https://example.com/rev-gs-cache")
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "6" * 64,
        captured_at=datetime(2026, 3, 1, tzinfo=UTC),
        content_cache_uri="gs://bucket/path.json",
    )
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/source-revisions/{rev.source_revision_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "gs://bucket/path.json" in r.text
    assert 'href="gs://bucket/path.json"' not in r.text


# ---------------------------------------------------------------------------
# POST /dashboard/source-revisions/{id}/clear-cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_cache_unauthenticated_redirects(client, session):
    src = _make_source("https://example.com/cache-unauth")
    session.add(src)
    await session.flush()
    rev = _make_revision(src)
    session.add(rev)
    await session.flush()

    r = await client.post(
        f"/dashboard/source-revisions/{rev.source_revision_id}/clear-cache",
        follow_redirects=False,
    )
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_clear_cache_clears_fields_and_redirects(client, session):
    src = _make_source("https://example.com/cache-clear")
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "e" * 64,
        captured_at=datetime(2026, 3, 1, tzinfo=UTC),
        content_cache_uri="gs://bucket/path.json",
        content_cache_expires_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.post(
        f"/dashboard/source-revisions/{rev.source_revision_id}/clear-cache",
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    await session.refresh(rev)
    assert rev.content_cache_uri is None
    assert rev.content_cache_expires_at is None


@pytest.mark.asyncio
async def test_clear_cache_htmx_returns_partial_and_flash(client, session):
    """HTMX clear-cache re-renders the card in place and fires a success toast (#78 #6)."""
    src = _make_source("https://example.com/cache-htmx")
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "f" * 64,
        captured_at=datetime(2026, 3, 1, tzinfo=UTC),
        content_cache_uri="gs://bucket/htmx.json",
        content_cache_expires_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.post(
        f"/dashboard/source-revisions/{rev.source_revision_id}/clear-cache",
        headers={**_HEADERS, "HX-Request": "true"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "showFlash" in r.headers.get("HX-Trigger", "")
    assert "not cached" in r.text
    # Focus moves to the heading after the swap (#78 CR3).
    assert 'getElementById("revision-heading")' in r.text
    await session.refresh(rev)
    assert rev.content_cache_uri is None
    assert rev.content_cache_expires_at is None
