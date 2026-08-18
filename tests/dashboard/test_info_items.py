"""Tests for /dashboard/info-items/ routes."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from ulid import ULID

from src.api.main import app
from src.core.models import (
    ChangesOutboxRow,
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoSource,
    ReplicationCommand,
    RepSpec,
    SourceRevision,
)
from src.core.models.domain import Domain

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
            "path_template": "items/{source_revision.id}.json",
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
async def test_detail_ulid_uses_shared_copyable_macro(client, session):
    """The ULID copy affordance uses the shared, hardened `copyable` macro
    (value bound via |tojson → writeText(v)), not an inline writeText('...')."""
    item = _make_item("Copyable Canary")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "navigator.clipboard" in r.text
    assert "writeText(v)" in r.text
    assert "writeText('" not in r.text


@pytest.mark.asyncio
async def test_detail_uses_entity_card_eyebrow(client, session):
    """InfoItem detail converges on the entity-card + eyebrow header (#81)."""
    item = _make_item("Eyebrow Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'class="eyebrow">Information Item<' in r.text
    assert "entity-card__header" in r.text
    assert 'aria-label="Breadcrumb"' not in r.text
    assert 'id="info-item-heading"' in r.text


@pytest.mark.asyncio
async def test_detail_revision_history_uses_status_pill(client, session):
    """Revision History cache column uses status-pill (cached/expired/missing),
    not badge--success, and captured_at is UTC-suffixed (#81)."""
    item = _make_item("Rev-Pill Item")
    session.add(item)
    await session.flush()
    source = _make_source("https://example.com/rev-pill")
    session.add(source)
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    rev = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + "a" * 10,
        captured_at=datetime(2026, 2, 3, 8, 15, tzinfo=UTC),
        content_cache_uri="gs://bucket/x.json",
    )
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "status-pill status-pill--cached" in r.text
    assert "badge--success" not in r.text
    assert "2026-02-03 08:15 UTC" in r.text


@pytest.mark.asyncio
async def test_detail_rep_spec_public_url_open_button(client, session):
    """Replicator assignment public_url gets an Open button; activated_at UTC (#81)."""
    item = _make_item("Pub-Open Item")
    session.add(item)
    await session.flush()
    rs = _make_rep_spec("Pub-Open Spec")
    session.add(rs)
    await session.flush()
    session.add(
        InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=rs.rep_spec_id,
            activated_at=datetime(2026, 2, 4, 9, 0, tzinfo=UTC),
            public_url="https://cdn.example.com/out.json",
        )
    )
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'href="https://cdn.example.com/out.json"' in r.text
    assert ">Open ↗</a>" in r.text
    assert "2026-02-04 09:00 UTC" in r.text


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
    # External-open affordance is a shared "Open ↗" button (modeled on Copy).
    assert 'href="https://example.com/tabbed"' in r.text
    assert ">Open ↗</a>" in r.text


@pytest.mark.asyncio
async def test_detail_shows_active_rep_spec_assignment(client, session):
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
    # Re-renders the assignments section (with focus move) rather than an empty 200 (#81 CR15).
    assert 'id="ii-rep-spec-assignments"' in r.text
    assert 'getElementById("ii-rep-spec-heading")' in r.text
    assert "No active Replication Spec assignments." in r.text  # last one removed

    await session.refresh(assignment)
    assert assignment.deactivated_at is not None

    # Idempotent: a repeat deactivate does not overwrite the timestamp (#81 CR14).
    first_ts = assignment.deactivated_at
    r2 = await client.delete(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}",
        headers=_HEADERS,
    )
    assert r2.status_code == 200
    await session.refresh(assignment)
    assert assignment.deactivated_at == first_ts


@pytest.mark.asyncio
async def test_deactivate_one_of_several_rerenders_remaining(client, session):
    """Deactivating one assignment re-renders the section with the others intact
    (multi-row branch of _rep_spec_assignments.html) (#81 CR16)."""
    item = _make_item("Multi-Assign Item")
    session.add(item)
    await session.flush()
    rs_keep = _make_rep_spec("Keep Spec")
    rs_drop = _make_rep_spec("Drop Spec")
    session.add(rs_keep)
    session.add(rs_drop)
    await session.flush()
    keep = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rs_keep.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    drop = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rs_drop.rep_spec_id,
        activated_at=datetime(2026, 4, 2, tzinfo=UTC),
    )
    session.add(keep)
    session.add(drop)
    await session.flush()

    r = await client.delete(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{drop.id}",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert 'id="ii-rep-spec-assignments"' in r.text
    assert "Keep Spec" in r.text
    assert "Drop Spec" not in r.text
    assert "No active Replication Spec assignments." not in r.text


# ---------------------------------------------------------------------------
# Replication state on the assignment table (archiver#171)
# ---------------------------------------------------------------------------
#
# `public_url` acquired an automated writer in #170. #143's rule — *do not ship
# a column that silently populates* — makes the manual edit a bug rather than a
# convenience: whatever an author typed, the next occasion overwrites.


async def _assigned(session, *, name: str, url: str, with_revision: bool = True, **rev):
    """An InfoItem bound to a fresh InfoSource with one active RepSpec assignment."""
    item = _make_item(name, rep_fields={})
    source = _make_source(url)
    rs = _make_rep_spec(f"{name} Spec")
    session.add_all([item, source, rs])
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rs.rep_spec_id,
        activated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    session.add(assignment)
    revision = None
    if with_revision:
        revision = SourceRevision(
            info_source_id=source.info_source_id,
            content_fingerprint="sha256:" + "f" * 64,
            captured_at=datetime(2026, 5, 2, tzinfo=UTC),
            content_cache_uri=rev.pop("content_cache_uri", "file:///blobs/f.bin"),
            source_media_type="text/html",
            **rev,
        )
        session.add(revision)
    await session.flush()
    return item, assignment, revision


def _command_for(assignment, revision, **kw) -> ReplicationCommand:
    return ReplicationCommand(
        command_id=kw.pop("command_id", "cmd-dash-1"),
        info_item_rep_spec_id=assignment.id,
        source_revision_id=revision.source_revision_id,
        info_source_id=revision.info_source_id,
        provider="gcs",
        credentials_alias="default",
        media_type="text/html",
        **kw,
    )


@pytest.mark.asyncio
async def test_public_url_is_no_longer_editable(client, session):
    """The inline form is gone: an author's URL was silently clobbered by the
    next occasion, which is worse than not offering the field."""
    item, assignment, revision = await _assigned(
        session, name="ReadOnly Item", url="https://example.com/readonly"
    )
    assignment.public_url = "https://cdn.example.com/readonly.json"
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert 'name="public_url"' not in r.text
    assert "/public-url" not in r.text
    assert "https://cdn.example.com/readonly.json" in r.text
    assert ">Open ↗</a>" in r.text


def test_the_public_url_patch_route_is_retired():
    """Gone from the route table, not merely unlinked from the template — a
    dashboard route with no UI is still a writable endpoint."""
    paths = {getattr(route, "path", "") for route in app.routes}
    assert not [p for p in paths if p.endswith("/public-url")]


@pytest.mark.asyncio
async def test_a_completed_occasion_renders_its_provenance(client, session):
    """Where the URL came from: the occasion's id, when it landed, and its state."""
    item, assignment, revision = await _assigned(
        session, name="Provenance Item", url="https://example.com/provenance"
    )
    assignment.public_url = "https://cdn.example.com/prov.json"
    session.add(
        _command_for(
            assignment,
            revision,
            command_id="cmd-provenance",
            state="complete",
            public_url="https://cdn.example.com/prov.json",
            closed_at=datetime(2026, 5, 3, 7, 30, tzinfo=UTC),
        )
    )
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert "cmd-provenance" in r.text
    assert "2026-05-03 07:30 UTC" in r.text
    assert "badge--success" in r.text


@pytest.mark.asyncio
async def test_a_skipped_occasion_renders_its_reason(client, session):
    """The whole point of persisting skips: an invisible refusal reads as "not
    replicated yet" forever."""
    item, assignment, revision = await _assigned(
        session, name="Skipped Item", url="https://example.com/skipped"
    )
    session.add(
        _command_for(
            assignment,
            revision,
            command_id="cmd-skipped",
            state="skipped",
            reason="blob_expired_locally",
            closed_at=datetime(2026, 5, 3, tzinfo=UTC),
        )
    )
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert "skipped" in r.text
    assert "blob_expired_locally" in r.text


@pytest.mark.asyncio
async def test_a_terminal_failure_renders_the_producer_reason(client, session):
    item, assignment, revision = await _assigned(
        session, name="Failed Item", url="https://example.com/failed"
    )
    session.add(
        _command_for(
            assignment,
            revision,
            command_id="cmd-failed",
            state="failed",
            reason="destination_forbidden",
            terminal=True,
            closed_at=datetime(2026, 5, 3, tzinfo=UTC),
        )
    )
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert "destination_forbidden" in r.text
    assert "badge--danger" in r.text


@pytest.mark.asyncio
async def test_an_assignment_with_no_occasion_says_so(client, session):
    item, _, _ = await _assigned(session, name="Never Item", url="https://example.com/never")

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert "Never replicated" in r.text


@pytest.mark.asyncio
async def test_the_assignment_table_columns_line_up(client, session):
    """#171's nit: the header declared five columns while the row rendered four."""
    item, _, _ = await _assigned(session, name="Columns Item", url="https://example.com/columns")

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    table = r.text.split('aria-label="Active Replication Spec assignments"')[1].split("</table>")[0]
    head, body = table.split("<tbody>")
    assert head.count('class="data-table__th"') == body.count('class="data-table__cell')


# ---------------------------------------------------------------------------
# POST /{item_id}/rep-spec-assignments/{aid}/replicate  (archiver#171)
# ---------------------------------------------------------------------------
#
# A new assignment on stable content never replicates: nothing issues until the
# next revision, which for a stable InfoItem may be never.


@pytest.mark.asyncio
async def test_replicate_now_issues_an_occasion_and_returns_the_row(client, session):
    item, assignment, revision = await _assigned(
        session, name="Replicate Item", url="https://example.com/replicate"
    )

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/replicate",
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert f'id="rs-row-{assignment.id}"' in r.text
    assert "requested" in r.text

    commands = (
        (
            await session.execute(
                select(ReplicationCommand).where(
                    ReplicationCommand.info_item_rep_spec_id == assignment.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [c.state for c in commands] == ["requested"]
    assert commands[0].source_revision_id == revision.source_revision_id


@pytest.mark.asyncio
async def test_replicate_now_enqueues_the_command_on_the_outbox(client, session):
    """The button is the same transactional path as the automatic one — it does
    not publish, it enqueues."""
    item, assignment, _ = await _assigned(
        session, name="Outbox Item", url="https://example.com/outbox"
    )

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/replicate",
        headers=_HEADERS,
    )

    assert r.status_code == 200
    rows = (
        (
            await session.execute(
                select(ChangesOutboxRow).where(ChangesOutboxRow.topic == "content.replicate")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_replicate_now_renders_the_skip_rather_than_erroring(client, session):
    """A refused occasion is recorded and shown — the operator asked, and got an
    answer, not a 500."""
    item, assignment, _ = await _assigned(
        session,
        name="Blobless Item",
        url="https://example.com/blobless",
        content_cache_uri=None,
    )

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/replicate",
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert "blob_absent" in r.text


@pytest.mark.asyncio
async def test_replicate_now_refuses_when_there_is_nothing_captured_yet(client, session):
    item, assignment, _ = await _assigned(
        session,
        name="Uncaptured Item",
        url="https://example.com/uncaptured",
        with_revision=False,
    )

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/replicate",
        headers=_HEADERS,
    )

    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["code"] == "no_revision"


@pytest.mark.asyncio
async def test_replicate_now_rejects_a_foreign_assignment(client, session):
    """The assignment id is untrusted input; it must belong to this item."""
    _, assignment, _ = await _assigned(session, name="Owner Item", url="https://example.com/owner")
    other = _make_item("Other Item")
    session.add(other)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{other.info_item_id}/rep-spec-assignments/{assignment.id}/replicate",
        headers=_HEADERS,
    )

    assert r.status_code == 404


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
async def test_hub_detail_sources_table_shows_spec_summary(client, session):
    """Spec lives in the Information Sources bindings table, not the Watcher section (#62)."""
    item = _make_item("Hub Spec Item")
    src = _make_source("https://hub-spec.example.com/page")  # _spec() → algorithm full_page
    session.add_all([item, src])
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    # Spec column header + summary derived from the InfoSource's source_specs.
    assert ">Spec</th>" in r.text
    assert "full_page · 1 spec" in r.text


@pytest.mark.asyncio
async def test_hub_detail_shows_replicator_section(client, session):
    item = _make_item("Hub Replicator Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Replicator" in r.text


@pytest.mark.asyncio
async def test_hub_detail_watcher_header_is_never_a_deeplink(client, session, monkeypatch):
    """The per-item Watcher deeplink retired with archiver#142.

    It was keyed on `watcher_item_id` — Watcher's primary key, which
    announcements never handed back — so there was no per-item URL left to build
    even with both base URLs configured, and the column itself is now gone.
    Asserting the *absence* rather than deleting the test: a reintroduced link
    would silently 404 for every announced item, worse than no link at all.
    """
    monkeypatch.setenv("WATCHER_PUBLIC_BASE_URL", "https://watcher.exe.xyz:8000")
    monkeypatch.setenv("WATCHER_BASE_URL", "http://localhost:8000")
    item = _make_item("Watched Hub Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    # The section heading survives; the anchor does not.
    assert "Watcher" in r.text
    assert "/watched-items/" not in r.text
    assert "watcher.exe.xyz" not in r.text
    assert "localhost:8000" not in r.text


@pytest.mark.asyncio
async def test_hub_detail_shows_revision_history(client, session):
    """Revision History is sourced from source_revisions across the item's
    InfoSource bindings — no explicit info_item_source_revisions pin needed (#101)."""
    item = _make_item("Hub History Item")
    src = _make_source("https://hub.example.com/hist")
    session.add_all([item, src])
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "d" * 64,
        captured_at=datetime.now(UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Revision History" in r.text
    # Rendered from the binding, with NO pin row present:
    assert rev.content_fingerprint[:20] in r.text
    assert "https://hub.example.com/hist" in r.text


@pytest.mark.asyncio
async def test_hub_detail_revision_history_includes_previous_primary(client, session):
    """Revisions captured on a now-deactivated (previous primary) binding still
    appear in the item's Revision History — succession-aware, newest first (#101)."""
    item = _make_item("Succession Item")
    old_src = _make_source("https://old.example.com/page")
    new_src = _make_source("https://new.example.com/page")
    session.add_all([item, old_src, new_src])
    await session.flush()
    # Previous primary (deactivated) + current primary (active) bindings.
    session.add_all(
        [
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=old_src.info_source_id,
                deactivated_at=datetime(2026, 1, 15, tzinfo=UTC),
            ),
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=new_src.info_source_id,
            ),
        ]
    )
    old_rev = SourceRevision(
        info_source_id=old_src.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    new_rev = SourceRevision(
        info_source_id=new_src.info_source_id,
        content_fingerprint="sha256:" + "b" * 64,
        captured_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    session.add_all([old_rev, new_rev])
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert r.status_code == 200
    # Both the previous-primary and current-primary revisions are listed.
    assert "https://old.example.com/page" in r.text
    assert "https://new.example.com/page" in r.text
    assert old_rev.content_fingerprint[:20] in r.text
    assert new_rev.content_fingerprint[:20] in r.text
    # Newest first: current-primary revision precedes the previous-primary one.
    assert r.text.index(new_rev.content_fingerprint[:20]) < r.text.index(
        old_rev.content_fingerprint[:20]
    )


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
