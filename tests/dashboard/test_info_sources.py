"""Tests for /dashboard/info-sources/ routes."""

import json
from datetime import UTC, datetime

import pytest
from ulid import ULID

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
    r = await client.get(f"/dashboard/info-sources/{ULID()}", headers=_HEADERS)
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_detail_shows_url(client, session):
    src = _make_source("https://example.com/spec-display")
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "https://example.com/spec-display" in r.text


@pytest.mark.asyncio
async def test_detail_uses_entity_card_eyebrow(client, session):
    """InfoSource detail converges on entity-card + eyebrow; grid uses __item (#79)."""
    src = _make_source("https://example.com/eyebrow-src")
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'class="eyebrow">Information Source<' in r.text
    assert "entity-card__header" in r.text
    assert 'aria-label="Breadcrumb"' not in r.text
    assert 'id="info-source-heading"' in r.text
    # detail-grid uses __item wrappers, not bare <dl><dt><dd> (the misalignment bug).
    assert "<dt>" not in r.text


@pytest.mark.asyncio
async def test_detail_id_copyable_and_url_open_button(client, session):
    """InfoSource id is copyable (shared macro) and the URL has an Open button (#79)."""
    src = _make_source("https://example.com/copy-open-src")
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "writeText(v)" in r.text
    assert 'href="https://example.com/copy-open-src"' in r.text
    assert ">Open ↗</a>" in r.text


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


@pytest.mark.asyncio
async def test_detail_shows_sibling_sources_at_same_url(client, session):
    """Finding #8: cross-link other InfoSources sharing this URL."""
    url = "https://example.com/shared-url"
    src = _make_source(url)
    sibling = _make_source(url)
    other = _make_source("https://example.com/unrelated-url")
    session.add_all([src, sibling, other])
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Other Sources at This URL" in r.text
    # Sibling is linked; self and unrelated source are not listed here.
    assert f"/dashboard/info-sources/{sibling.info_source_id}" in r.text
    assert str(other.info_source_id) not in r.text


@pytest.mark.asyncio
async def test_detail_hides_sibling_section_when_no_siblings(client, session):
    """No other sources at the URL → section absent."""
    src = _make_source("https://example.com/lonely-url")
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Other Sources at This URL" not in r.text


@pytest.mark.asyncio
async def test_detail_sibling_count_caps_at_fifty_plus(client, session):
    """More than 50 siblings → heading shows '(50+)' via a limit+1 probe (#79 CR 4)."""
    url = "https://example.com/crowded-url"
    src = _make_source(url)
    session.add(src)
    # 51 other sources at the same URL → display caps at 50, count reads "50+".
    session.add_all([_make_source(url) for _ in range(51)])
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Other Sources at This URL (50+)" in r.text


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


# ---------------------------------------------------------------------------
# POST /dashboard/info-sources/{id}/source-specs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_specs_valid_redirects(client, session):
    src = _make_source("https://example.com/update-specs-ok")
    session.add(src)
    await session.flush()

    xpath_spec = {
        "schema_version": 1,
        "extraction": {"algorithm": "xpath", "selector": "//h1"},
        "fingerprint": {},
    }
    specs = json.dumps([_spec("css"), xpath_spec])
    r = await client.post(
        f"/dashboard/info-sources/{src.info_source_id}/source-specs",
        data={"source_specs": specs},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)


@pytest.mark.asyncio
async def test_update_specs_invalid_json_rerenders_html_with_error(client, session):
    """Invalid JSON → re-renders detail page HTML with inline error (not JSON body)."""
    src = _make_source("https://example.com/update-specs-bad-json")
    session.add(src)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-sources/{src.info_source_id}/source-specs",
        data={"source_specs": "not-valid-json"},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 422
    assert "text/html" in r.headers["content-type"]
    assert "JSON" in r.text  # error message visible in page


@pytest.mark.asyncio
async def test_update_specs_schema_error_rerenders_html_with_error(client, session):
    """Schema-invalid spec → re-renders detail page HTML (not JSON envelope)."""
    src = _make_source("https://example.com/update-specs-schema-err")
    session.add(src)
    await session.flush()

    # css requires selector — missing it makes it schema-invalid
    bad_specs = json.dumps([{"schema_version": 1, "extraction": {"algorithm": "css"}}])
    r = await client.post(
        f"/dashboard/info-sources/{src.info_source_id}/source-specs",
        data={"source_specs": bad_specs},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 422
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_update_specs_htmx_swaps_card_and_flashes(client, session):
    """Finding #7: HTMX success swaps the specs card in place + fires a success toast."""
    src = _make_source("https://example.com/update-specs-htmx-ok")
    session.add(src)
    await session.flush()

    xpath_spec = {
        "schema_version": 1,
        "extraction": {"algorithm": "xpath", "selector": "//h2"},
        "fingerprint": {},
    }
    specs = json.dumps([xpath_spec])
    r = await client.post(
        f"/dashboard/info-sources/{src.info_source_id}/source-specs",
        data={"source_specs": specs},
        headers={**_HEADERS, "HX-Request": "true"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "showFlash" in r.headers.get("HX-Trigger", "")
    # Card partial swapped in place — id target present, not a full page.
    assert 'id="source-specs-card"' in r.text
    assert "<h1" not in r.text
    # Reflects the newly-saved spec.
    assert "//h2" in r.text
    await session.refresh(src)
    assert src.source_specs == [xpath_spec]


@pytest.mark.asyncio
async def test_update_specs_htmx_error_swaps_card_with_inline_error(client, session):
    """HTMX validation error swaps the card back with the inline error (200 so htmx swaps)."""
    src = _make_source("https://example.com/update-specs-htmx-err")
    session.add(src)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-sources/{src.info_source_id}/source-specs",
        data={"source_specs": "not-valid-json{oops"},
        headers={**_HEADERS, "HX-Request": "true"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert 'id="source-specs-card"' in r.text
    assert "JSON" in r.text  # inline error visible
    assert "<h1" not in r.text  # partial, not full page
    # Error is announced (role="alert") and focus moves to the heading (#79 CR 1,2).
    assert 'role="alert"' in r.text
    assert 'getElementById("source-specs-heading")' in r.text
    # Submitted (invalid) text is preserved in the textarea, not discarded (#79 CR 3).
    assert "not-valid-json{oops" in r.text


@pytest.mark.asyncio
async def test_update_specs_nonhtmx_error_preserves_submitted_text(client, session):
    """Non-HTMX 422 re-render also echoes the submitted invalid text back (#79 CR 3)."""
    src = _make_source("https://example.com/update-specs-nonhtmx-preserve")
    session.add(src)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-sources/{src.info_source_id}/source-specs",
        data={"source_specs": "still-bad-json{"},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 422
    assert "still-bad-json{" in r.text
