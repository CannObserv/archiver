"""Tests for /dashboard/info-items/ routes."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoItemSourceRevision,
    InfoSource,
    RepSpec,
    SourceRevision,
)

_HEADERS = {"X-ExeDev-UserID": "ext-items", "X-ExeDev-Email": "items@example.com"}
_LIST_URL = "/dashboard/info-items/"
_NEW_URL = "/dashboard/info-items/new"


def _spec() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


def _make_item(name: str = "Test Item", **kw) -> InfoItem:
    return InfoItem(name=name, **kw)


def _make_source(url: str = "https://example.com/page") -> InfoSource:
    return InfoSource(url=url, source_specs=[_spec()])


def _make_rep_spec(name: str = "Test Spec") -> RepSpec:
    return RepSpec(
        provider="gcs",
        name=name,
        schema_version=1,
        document={
            "provider": "gcs",
            "version": 1,
            "credentials_alias": "default",
            "bucket": "test-bucket",
            "path_template": "items/{info_item_id}.json",
            "required_fields": [],
        },
    )


# ---------------------------------------------------------------------------
# GET /dashboard/info-items/
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
async def test_list_shows_item_names(client, session):
    item = _make_item("Visible Item")
    session.add(item)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "Visible Item" in r.text


@pytest.mark.asyncio
async def test_list_name_contains_filter(client, session):
    session.add(_make_item("Alpha Canary"))
    session.add(_make_item("Beta Kestrel"))
    await session.flush()

    r = await client.get(_LIST_URL + "?name_contains=Canary", headers=_HEADERS)
    assert r.status_code == 200
    assert "Alpha Canary" in r.text
    assert "Beta Kestrel" not in r.text


@pytest.mark.asyncio
async def test_list_shows_primary_url(client, session):
    item = _make_item("URL Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/url-item")
    session.add(source)
    await session.flush()
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
    )
    session.add(binding)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert "https://example.com/url-item" in r.text


# ---------------------------------------------------------------------------
# GET /dashboard/info-items/ — #47 UI/UX updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_no_search_by_name_label(client):
    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "Search by name" not in r.text


@pytest.mark.asyncio
async def test_list_information_source_column_header(client, session):
    session.add(_make_item("Col Header Item"))
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "Information Source" in r.text
    assert "Primary Source URL" not in r.text


@pytest.mark.asyncio
async def test_list_no_active_rep_specs_column(client, session):
    session.add(_make_item("No RepSpec Col Item"))
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "Active Rep Specs" not in r.text


@pytest.mark.asyncio
async def test_list_no_created_column(client, session):
    session.add(_make_item("No Created Col Item"))
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert ">Created<" not in r.text


@pytest.mark.asyncio
async def test_list_observed_column_header(client, session):
    session.add(_make_item("Observed Col Item"))
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "Observed" in r.text


@pytest.mark.asyncio
async def test_list_primary_source_links_to_info_source_detail(client, session):
    item = _make_item("Linked Source Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/linked-src")
    session.add(source)
    await session.flush()
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
    )
    session.add(binding)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert f"/dashboard/info-sources/{source.info_source_id}" in r.text


@pytest.mark.asyncio
async def test_list_observed_shows_captured_at_for_primary_source(client, session):
    from datetime import UTC, datetime

    item = _make_item("Observed Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/observed-src")
    session.add(source)
    await session.flush()
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
    )
    session.add(binding)
    await session.flush()
    rev = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:deadbeef01",
        captured_at=datetime(2026, 5, 15, 10, 30, 0, tzinfo=UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "2026-05-15 10:30" in r.text


@pytest.mark.asyncio
async def test_list_observed_dash_when_no_revision(client, session):
    item = _make_item("No Rev Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/no-rev-src")
    session.add(source)
    await session.flush()
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
    )
    session.add(binding)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "Observed" in r.text
    assert "—" in r.text


# ---------------------------------------------------------------------------
# GET /dashboard/info-items/new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_unauthenticated_redirects(client):
    r = await client.get(_NEW_URL, follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_new_redirects_to_register(client):
    r = await client.get(_NEW_URL, headers=_HEADERS, follow_redirects=False)
    assert r.status_code == 301
    assert "/dashboard/register" in r.headers.get("location", "")


# ---------------------------------------------------------------------------
# POST /dashboard/info-items/new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_minimal_redirects_to_detail(client, session):
    r = await client.post(
        _NEW_URL,
        data={"name": "Created Item", "rep_fields": "{}"},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "/dashboard/info-items/" in r.headers["location"]

    result = await session.execute(select(InfoItem).where(InfoItem.name == "Created Item"))
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_create_unauthenticated_redirects(client):
    r = await client.post(
        _NEW_URL,
        data={"name": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_create_missing_name_returns_error(client):
    r = await client.post(
        _NEW_URL,
        data={"name": "", "rep_fields": "{}"},
        headers=_HEADERS,
    )
    assert r.status_code in (200, 422)  # re-renders form with error


@pytest.mark.asyncio
async def test_create_with_source_spec_creates_binding(client, session):
    specs = json.dumps([_spec()])
    r = await client.post(
        _NEW_URL,
        data={
            "name": "Item With Source",
            "rep_fields": "{}",
            "initial_url": "https://example.com/new-item-src",
            "initial_source_specs": specs,
        },
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)

    result = await session.execute(select(InfoItem).where(InfoItem.name == "Item With Source"))
    item = result.scalar_one()
    bindings = (
        (
            await session.execute(
                select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(bindings) == 1


# ---------------------------------------------------------------------------
# GET /dashboard/info-items/{item_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_unauthenticated_redirects(client, session):
    item = _make_item("Auth Detail Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_detail_not_found_returns_404(client):
    from ulid import ULID

    fake_id = str(ULID())
    r = await client.get(f"/dashboard/info-items/{fake_id}", headers=_HEADERS)
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_detail_returns_200_with_name(client, session):
    item = _make_item("Detail Canary")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Detail Canary" in r.text


@pytest.mark.asyncio
async def test_detail_shows_active_source_binding(client, session):
    item = _make_item("Tabbed Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/tabbed")
    session.add(source)
    await session.flush()
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
    )
    session.add(binding)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "https://example.com/tabbed" in r.text


@pytest.mark.asyncio
async def test_detail_shows_active_rep_spec_assignment(client, session):
    from datetime import UTC, datetime

    item = _make_item("Rep Spec Item")
    session.add(item)
    await session.flush()
    rs = _make_rep_spec("My Spec")
    session.add(rs)
    await session.flush()
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rs.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "My Spec" in r.text


# ---------------------------------------------------------------------------
# POST /{item_id}/bind-source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_source_creates_binding(client, session):
    item = _make_item("Bind Source Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/bind-src")
    session.add(source)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/bind-source",
        data={"info_source_id": str(source.info_source_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)

    result = await session.execute(
        select(InfoItemSource).where(
            InfoItemSource.info_item_id == item.info_item_id,
            InfoItemSource.info_source_id == source.info_source_id,
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_bind_source_unknown_item_returns_404(client):
    from ulid import ULID

    fake_id = str(ULID())
    r = await client.post(
        f"/dashboard/info-items/{fake_id}/bind-source",
        data={"info_source_id": str(ULID())},
        headers=_HEADERS,
    )
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


# ---------------------------------------------------------------------------
# DELETE /{item_id}/info-sources/{source_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_source_binding(client, session):
    item = _make_item("Deact Source Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/deact-src")
    session.add(source)
    await session.flush()
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
    )
    session.add(binding)
    await session.flush()

    r = await client.delete(
        f"/dashboard/info-items/{item.info_item_id}/info-sources/{source.info_source_id}",
        headers=_HEADERS,
    )
    assert r.status_code == 200

    await session.refresh(binding)
    assert binding.deactivated_at is not None


# ---------------------------------------------------------------------------
# POST /{item_id}/assign-rep-spec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_rep_spec_creates_assignment(client, session):
    item = _make_item("Assign RS Item")
    session.add(item)
    await session.flush()
    rs = _make_rep_spec()
    session.add(rs)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/assign-rep-spec",
        data={"rep_spec_id": str(rs.rep_spec_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)

    result = await session.execute(
        select(InfoItemRepSpec).where(
            InfoItemRepSpec.info_item_id == item.info_item_id,
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_assign_rep_spec_unknown_item_returns_404(client):
    from ulid import ULID

    fake_id = str(ULID())
    r = await client.post(
        f"/dashboard/info-items/{fake_id}/assign-rep-spec",
        data={"rep_spec_id": str(ULID())},
        headers=_HEADERS,
    )
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


# ---------------------------------------------------------------------------
# DELETE /{item_id}/rep-spec-assignments/{aid}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_rep_spec_assignment(client, session):
    from datetime import UTC, datetime

    item = _make_item("Deact RS Item")
    session.add(item)
    await session.flush()
    rs = _make_rep_spec()
    session.add(rs)
    await session.flush()
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rs.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.flush()

    r = await client.delete(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}",
        headers=_HEADERS,
    )
    assert r.status_code == 200

    await session.refresh(assignment)
    assert assignment.deactivated_at is not None


# ---------------------------------------------------------------------------
# PATCH /{item_id}/rep-spec-assignments/{aid}/public-url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_public_url_returns_fragment(client, session):
    from datetime import UTC, datetime

    item = _make_item("Pub URL Item")
    session.add(item)
    await session.flush()
    rs = _make_rep_spec("Pub URL Spec")
    session.add(rs)
    await session.flush()
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rs.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/public-url",
        data={"public_url": "https://storage.example.com/item.json"},
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "https://storage.example.com/item.json" in r.text

    await session.refresh(assignment)
    assert assignment.public_url == "https://storage.example.com/item.json"


# ---------------------------------------------------------------------------
# POST /{item_id}/bind-revision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_revision_creates_binding(client, session):
    from datetime import UTC, datetime

    item = _make_item("Rev Bind Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/rev-bind")
    session.add(source)
    await session.flush()
    rev = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:aabbcc",
        captured_at=datetime.now(UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/bind-revision",
        data={"source_revision_id": str(rev.source_revision_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)

    result = await session.execute(
        select(InfoItemSourceRevision).where(
            InfoItemSourceRevision.info_item_id == item.info_item_id,
            InfoItemSourceRevision.source_revision_id == rev.source_revision_id,
        )
    )
    assert result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Hub page — 5-section vertical scroll (#49)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hub_detail_shows_overview_section(client, session):
    item = _make_item("Hub Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Hub Item" in r.text
    assert str(item.info_item_id) in r.text


@pytest.mark.asyncio
async def test_hub_detail_shows_sources_section(client, session):
    item = _make_item("Hub Sources Item")
    src = _make_source("https://hub.example.com/page")
    session.add_all([item, src])
    await session.flush()
    binding = InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id)
    session.add(binding)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "https://hub.example.com/page" in r.text
    assert "Information Sources" in r.text


@pytest.mark.asyncio
async def test_hub_detail_shows_replicator_section(client, session):
    item = _make_item("Hub Replicator Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Replicator" in r.text


@pytest.mark.asyncio
async def test_hub_detail_watcher_header_links_to_watcher(client, session, monkeypatch):
    """Watched item → "Watcher" header is a deeplink; public base URL wins (#62)."""
    monkeypatch.setenv("WATCHER_PUBLIC_BASE_URL", "https://watcher.exe.xyz:8000")
    monkeypatch.setenv("WATCHER_BASE_URL", "http://localhost:8000")
    item = _make_item("Watched Hub Item", watcher_item_id="01HZZWATCHER00000000000001")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "https://watcher.exe.xyz:8000/watched-items/01HZZWATCHER00000000000001" in r.text
    # Internal base must not leak into the browser deeplink.
    assert "localhost:8000" not in r.text


@pytest.mark.asyncio
async def test_hub_detail_watcher_header_plain_when_not_watched(client, session, monkeypatch):
    """Unwatched item (watcher_item_id is NULL) → plain "Watcher" header, no link."""
    monkeypatch.setenv("WATCHER_PUBLIC_BASE_URL", "https://watcher.exe.xyz:8000")
    item = _make_item("Unwatched Hub Item", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Watcher" in r.text
    assert "/watched-items/" not in r.text


@pytest.mark.asyncio
async def test_hub_detail_shows_revision_history(client, session):
    item = _make_item("Hub History Item")
    src = _make_source("https://hub.example.com/hist")
    session.add_all([item, src])
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "d" * 64,
        captured_at=datetime.now(UTC),
    )
    session.add(rev)
    await session.flush()
    hist = InfoItemSourceRevision(
        info_item_id=item.info_item_id,
        source_revision_id=rev.source_revision_id,
        bound_at=datetime.now(UTC),
    )
    session.add(hist)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Revision History" in r.text


@pytest.mark.asyncio
async def test_rep_fields_inline_save(client, session):
    item = _make_item("Rep Fields Item")
    session.add(item)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data={"rep_fields": '{"key1":"value1"}'},
    )
    assert r.status_code in (200, 303)

    await session.refresh(item)
    assert item.rep_fields == {"key1": "value1"}


# ---------------------------------------------------------------------------
# GET /{item_id}/suggest-rep-fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_rep_fields_no_domain_returns_empty(client, session):
    """Item with no active source binding returns empty suggestions."""
    item = _make_item("No Source Item")
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/suggest-rep-fields",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "No rep_fields suggestions" in r.text


@pytest.mark.asyncio
async def test_suggest_rep_fields_returns_domain_keys(client, session):
    """Domain-scoped rep_fields keys appear as sortableChips data island."""
    from src.core.models.domain import Domain

    domain = Domain(name="repfields.example.com")
    session.add(domain)
    await session.flush()

    # Peer item with rep_fields on the same domain
    peer = _make_item("Peer Item")
    peer.rep_fields = {"canonical_url": "", "headline": ""}
    session.add(peer)
    await session.flush()

    peer_src = InfoSource(
        url="https://repfields.example.com/peer",
        source_specs=[_spec()],
        domain_name="repfields.example.com",
    )
    session.add(peer_src)
    await session.flush()

    peer_binding = InfoItemSource(
        info_item_id=peer.info_item_id,
        info_source_id=peer_src.info_source_id,
    )
    session.add(peer_binding)
    await session.flush()

    # Target item bound to the same domain
    target = _make_item("Target Item")
    session.add(target)
    await session.flush()

    target_src = InfoSource(
        url="https://repfields.example.com/target",
        source_specs=[_spec()],
        domain_name="repfields.example.com",
    )
    session.add(target_src)
    await session.flush()

    target_binding = InfoItemSource(
        info_item_id=target.info_item_id,
        info_source_id=target_src.info_source_id,
    )
    session.add(target_binding)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{target.info_item_id}/suggest-rep-fields",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    # Both keys from the peer item should appear in the JSON data island
    assert "canonical_url" in r.text
    assert "headline" in r.text
