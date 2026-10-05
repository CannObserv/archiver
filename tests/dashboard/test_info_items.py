"""Tests for /dashboard/info-items/ routes."""

import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser

import pytest
from sqlalchemy import func, select
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
from src.core.services.replication_issuance import ManualIssuanceError
from src.core.tools.assign_rep_spec import assign_rep_spec
from src.dashboard.routes import info_items as info_items_routes
from tests.dashboard.conftest import (
    outside_action_sync_violations,
    poll_sync_violations,
    read_flash,
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
# The Replication section's Add-a-spec picker  (archiver#308)
# ---------------------------------------------------------------------------
#
# Replaced the `<details>` ULID form and its full-page POST. Every spec not
# actively assigned, each with its readiness and the path it would render;
# Assign posts over HTMX, returns the picker and fires `replicationChanged`.
# Refusals - #301's 422/409s - render inline at 200 (docs/STYLE.md).


def _picker_block(html: str) -> str:
    """The picker alone, from its root to its closing marker."""
    start = html.index('id="ii-rep-spec-picker"')
    return html[start : html.index("<!-- /ii-rep-spec-picker -->", start)]


def _picker_entry(html: str, rs: RepSpec) -> str:
    """One spec's row in the picker."""
    start = html.index(f'id="picker-{rs.rep_spec_id}"')
    return html[start : html.index("</tr>", start)]


def _assign_disabled(entry: str) -> bool:
    """Whether the entry's Assign button carries ``disabled`` (not ``hx-disabled-elt``)."""
    tag = entry[entry.index('<button type="submit"') :]
    tag = tag[: tag.index(">")]
    return re.search(r"\sdisabled(\s|$)", tag) is not None


def _rep_spec_requiring(name: str, *required: str, path_template: str, **kw) -> RepSpec:
    rs = _make_rep_spec(name)
    rs.document = {**rs.document, "required_fields": list(required), "path_template": path_template}
    for key, value in kw.items():
        setattr(rs, key, value)
    return rs


async def _bound_item(session, name: str, bag: dict, *, with_revision: bool = True):
    """An InfoItem with an active source and, by default, one captured revision."""
    item = _make_item(name, rep_fields=bag)
    source = _make_source(f"https://example.com/{name.lower().replace(' ', '-')}")
    session.add_all([item, source])
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    revision = None
    if with_revision:
        revision = SourceRevision(
            info_source_id=source.info_source_id,
            content_fingerprint="sha256:" + "c" * 64,
            captured_at=datetime(2026, 5, 2, tzinfo=UTC),
            content_cache_uri="file:///blobs/c.bin",
            source_media_type="text/html",
        )
        session.add(revision)
    await session.flush()
    return item, revision


def _picker_url(item: InfoItem) -> str:
    return f"/dashboard/info-items/{item.info_item_id}/rep-spec-picker"


async def _assign(client, item: InfoItem, rs: RepSpec | str):
    rep_spec_id = rs if isinstance(rs, str) else str(rs.rep_spec_id)
    return await client.post(
        f"{_picker_url(item)}/assign", data={"rep_spec_id": rep_spec_id}, headers=_HEADERS
    )


_ORG_PREVIEW_PATH = "organizations/{org.title_slug}/{source_revision.id}.{source_revision.ext}"


@pytest.mark.asyncio
async def test_the_picker_lists_only_the_specs_not_actively_assigned(client, session):
    assigned = _make_rep_spec("Already Here")
    item = await _item_assigned_to(session, {}, assigned)
    offered = _make_rep_spec("Offered Spec")
    session.add(offered)
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    assert r.status_code == 200
    entry = _picker_entry(r.text, offered)
    assert f'href="/dashboard/rep-specs/{offered.rep_spec_id}"' in entry
    assert "Offered Spec" in entry
    assert '<span class="badge badge--sm">gcs</span>' in entry
    assert f'id="picker-{assigned.rep_spec_id}"' not in r.text


@pytest.mark.asyncio
async def test_a_ready_spec_previews_its_path_against_the_latest_revision(client, session):
    item, revision = await _bound_item(session, "Ready Picker", {"org": {"title": "WSLCB"}})
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PREVIEW_PATH)
    session.add(rs)
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    entry = _picker_entry(r.text, rs)
    assert "Ready" in entry
    assert f"organizations/wslcb/{revision.source_revision_id}.html" in entry
    assert "latest revision" in _picker_block(r.text)
    assert "Example occasion" not in _picker_block(r.text)
    assert not _assign_disabled(entry)


@pytest.mark.asyncio
async def test_with_no_revision_the_preview_is_a_labelled_example(client, session):
    item, _ = await _bound_item(
        session, "Example Picker", {"org": {"title": "WSLCB"}}, with_revision=False
    )
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PREVIEW_PATH)
    session.add(rs)
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    assert f"organizations/wslcb/{'0' * 26}.html" in _picker_entry(r.text, rs)
    assert "Example occasion" in _picker_block(r.text)


@pytest.mark.asyncio
async def test_a_spec_missing_keys_names_them_and_offers_to_show_them(client, session):
    item = _make_item("Needs Picker", rep_fields={})
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PREVIEW_PATH)
    session.add_all([item, rs])
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    entry = _picker_entry(r.text, rs)
    assert "Needs" in entry
    assert "<code>org.title</code>" in entry
    # The template stands in for a path it cannot render yet.
    assert _ORG_PREVIEW_PATH in entry
    assert _assign_disabled(entry)
    url = f"/dashboard/info-items/{item.info_item_id}/rep-fields?selected_spec={rs.rep_spec_id}"
    assert f'hx-get="{url}&amp;focus=true"' in entry
    assert 'hx-target="#ii-rep-fields"' in entry


@pytest.mark.asyncio
async def test_a_spec_that_cannot_render_shows_the_gates_reason(client, session):
    """archiver#312's wording, verbatim."""
    item = _make_item("Slugless Picker", rep_fields={"org": {"title": "!!!"}})
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PREVIEW_PATH)
    session.add_all([item, rs])
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    entry = _picker_entry(r.text, rs)
    assert "Can’t render" in entry
    assert "org.title &#34;!!!&#34; slugs to nothing (org.title_slug)" in entry
    assert "selected_spec=" in entry


@pytest.mark.asyncio
async def test_an_unwritable_provider_is_disabled_with_its_reason(client, session):
    item = _make_item("Unwritable Picker", rep_fields={})
    rs = _make_rep_spec("Archive Spec")
    rs.provider = "ia"
    session.add_all([item, rs])
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    entry = _picker_entry(r.text, rs)
    assert "Replicator has no Internet Archive writer yet" in entry
    assert _assign_disabled(entry)
    assert "selected_spec=" not in entry


@pytest.mark.asyncio
async def test_with_no_specs_at_all_the_picker_is_the_empty_state(client, session):
    assert await session.scalar(select(func.count()).select_from(RepSpec)) == 0
    item = _make_item("Empty Picker")
    session.add(item)
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    block = _picker_block(r.text)
    assert "No Replication Specs yet" in block
    assert 'href="/dashboard/rep-specs/new"' in block


@pytest.mark.asyncio
async def test_with_every_spec_assigned_the_picker_says_so(client, session):
    item = await _item_assigned_to(session, {}, _make_rep_spec("Only Spec"))

    r = await client.get(_picker_url(item), headers=_HEADERS)

    block = _picker_block(r.text)
    assert "Every Replication Spec is assigned" in block
    assert 'href="/dashboard/rep-specs/new"' in block


@pytest.mark.asyncio
async def test_the_picker_offers_a_new_spec_link_beside_its_list(client, session):
    item = _make_item("New Link Picker")
    session.add_all([item, _make_rep_spec("Some Spec")])
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    assert 'href="/dashboard/rep-specs/new"' in _picker_block(r.text)


@pytest.mark.asyncio
async def test_the_detail_page_carries_the_picker_and_not_the_ulid_form(client, session):
    item = _make_item("Picker Detail")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    block = _picker_block(r.text)
    assert 'id="ii-rep-spec-picker-heading"' in block
    assert "RepSpec ULID" not in r.text
    assert "assign-rep-spec" not in r.text


@pytest.mark.asyncio
async def test_the_picker_refetches_on_a_siblings_replication_change_only(client, session):
    item = _make_item("Listening Picker")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    block = _picker_block(r.text)
    root = block[: block.index(">")]
    assert f'hx-get="{_picker_url(item)}"' in root
    assert "replicationChanged[detail.source!=='picker'] from:body" in root
    assert 'hx-swap="outerHTML"' in root
    assert 'hx-disinherit="*"' in root


@pytest.mark.asyncio
async def test_a_picker_refetch_never_moves_focus_and_is_never_cached(client, session):
    item = _make_item("Refetch Picker")
    session.add(item)
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert 'getElementById("ii-rep-spec-picker-heading")' not in r.text


@pytest.mark.asyncio
async def test_assign_creates_the_assignment_and_fires_replication_changed(client, session):
    item, _ = await _bound_item(session, "Assign Picker", {})
    rs = _make_rep_spec("Assign Me")
    session.add(rs)
    await session.flush()

    r = await _assign(client, item, rs)

    assert r.status_code == 200
    triggers = read_flash(r)
    assert triggers["replicationChanged"] == {"source": "picker"}
    assert triggers["showFlash"] == {"level": "success", "body": "Assigned RepSpec 'Assign Me'."}
    assignment = (
        await session.execute(
            select(InfoItemRepSpec).where(InfoItemRepSpec.info_item_id == item.info_item_id)
        )
    ).scalar_one()
    assert assignment.rep_spec_id == rs.rep_spec_id
    # The picker comes back without the spec it just assigned, focused.
    assert 'id="ii-rep-spec-picker"' in r.text
    assert f'id="picker-{rs.rep_spec_id}"' not in r.text
    assert 'getElementById("ii-rep-spec-picker-heading")' in r.text


@pytest.mark.asyncio
async def test_assign_success_prompts_to_replicate_the_latest_revision(client, session):
    item, _ = await _bound_item(session, "Prompt Picker", {})
    rs = _make_rep_spec("Prompt Me")
    session.add(rs)
    await session.flush()

    r = await _assign(client, item, rs)

    assignment = (
        await session.execute(
            select(InfoItemRepSpec).where(InfoItemRepSpec.info_item_id == item.info_item_id)
        )
    ).scalar_one()
    assert "Replicate latest revision now?" in r.text
    url = (
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/replicate"
    )
    prompt = r.text[r.text.index("data-replicate-prompt") :]
    button = prompt[prompt.index("<button") : prompt.index(">", prompt.index("<button"))]
    assert f'hx-post="{url}"' in button
    assert "hx-confirm=" in button
    assert 'hx-disabled-elt="this"' in button
    assert 'hx-swap="outerHTML"' in button


@pytest.mark.asyncio
async def test_the_prompts_replicate_button_syncs_on_the_table_like_a_row_action(client, session):
    """It swaps the assignments table from outside it, so it races the table's
    poll as a row action does (archiver#220) - and syncs the same way."""
    item, _ = await _bound_item(session, "Prompt Sync Picker", {})
    rs = _make_rep_spec("Sync Me")
    session.add(rs)
    await session.flush()

    r = await _assign(client, item, rs)

    assert outside_action_sync_violations(r.text, "ii-rep-spec-assignments") == []


@pytest.mark.asyncio
async def test_assign_disables_its_button_in_flight(client, session):
    """CR 2. htmx reads hx-disabled-elt from the element that issues the
    request - the form - so on the button it guarded nothing, and a double
    click answered a success with "already assigned"."""
    item = _make_item("Double Click Picker")
    rs = _make_rep_spec("Click Once")
    session.add_all([item, rs])
    await session.flush()

    r = await client.get(_picker_url(item), headers=_HEADERS)

    entry = _picker_entry(r.text, rs)
    form = entry[entry.index("<form") :]
    assert 'hx-disabled-elt="find button"' in form[: form.index(">")]


@pytest.mark.asyncio
async def test_assign_with_no_revision_says_it_will_replicate_on_the_next(client, session):
    item, _ = await _bound_item(session, "No Revision Picker", {}, with_revision=False)
    rs = _make_rep_spec("Wait For It")
    session.add(rs)
    await session.flush()

    r = await _assign(client, item, rs)

    assert r.status_code == 200
    assert "will replicate on the next revision" in r.text
    assert "/replicate" not in r.text


@pytest.mark.asyncio
async def test_assign_leaves_the_spec_for_assign_rep_spec_to_load_under_its_lock(
    client, session, monkeypatch
):
    """CR 1. A RepSpec instance the route loaded first keeps its attributes when
    assign_rep_spec re-reads it FOR UPDATE (no populate_existing), so a draft
    edited in between would be gated on its old document and frozen on the new."""
    item, _ = await _bound_item(session, "Lock Order Picker", {})
    rs = _make_rep_spec("Lock Me")
    session.add(rs)
    await session.flush()
    session.expunge(rs)
    seen = []

    async def spy(db, **kw):
        seen.append(any(isinstance(o, RepSpec) for o in db.identity_map.values()))
        return await assign_rep_spec(db, **kw)

    monkeypatch.setattr(info_items_routes, "assign_rep_spec", spy)

    r = await _assign(client, item, rs)

    assert r.status_code == 200
    assert "replicationChanged" in read_flash(r)
    assert seen == [False]


@pytest.mark.asyncio
async def test_assign_refusal_names_the_missing_fields_inline(client, session):
    item = _make_item("Incomplete Picker", rep_fields={})
    rs = _rep_spec_requiring(
        "Needs org",
        "org.title",
        "org.acronym",
        path_template="o/{org.title}/{org.acronym}/{source_revision.id}.html",
    )
    session.add_all([item, rs])
    await session.flush()

    r = await _assign(client, item, rs)

    assert r.status_code == 200
    assert "replicationChanged" not in r.headers.get("HX-Trigger", "")
    refusal = r.text[r.text.index('id="picker-refusal"') :]
    assert "Needs org" in refusal
    assert "org.title" in refusal
    assert "org.acronym" in refusal
    assert await session.scalar(select(func.count()).select_from(InfoItemRepSpec)) == 0


@pytest.mark.asyncio
async def test_assign_refusal_gives_the_render_reason_inline(client, session):
    """Was an unhandled 500 before archiver#301."""
    item = _make_item("Unrenderable Picker", rep_fields={"org": {"name": "WA LCB"}})
    rs = _rep_spec_requiring(
        "Raw name", "org.name", path_template="archive/{org.name}/{source_revision.id}.html"
    )
    session.add_all([item, rs])
    await session.flush()

    r = await _assign(client, item, rs)

    assert r.status_code == 200
    refusal = r.text[r.text.index('id="picker-refusal"') :]
    assert "cannot render" in refusal
    assert "org.name" in refusal


@pytest.mark.asyncio
async def test_assign_refusal_names_the_raw_field_that_slugs_to_nothing(client, session):
    """archiver#312: the operator typed org.title, so the refusal names it."""
    item = _make_item("Slugless Assign Picker", rep_fields={"org": {"title": "!!!"}})
    rs = _rep_spec_requiring("Slugged title", "org.title_slug", path_template=_ORG_PREVIEW_PATH)
    session.add_all([item, rs])
    await session.flush()

    r = await _assign(client, item, rs)

    refusal = r.text[r.text.index('id="picker-refusal"') :]
    assert "cannot render" in refusal
    assert "org.title &#34;!!!&#34; slugs to nothing (org.title_slug)" in refusal
    assert "lack what" not in refusal


@pytest.mark.asyncio
async def test_assign_refuses_a_duplicate_inline(client, session):
    rs = _make_rep_spec("Shared Spec")
    item = await _item_assigned_to(session, {}, rs)

    r = await _assign(client, item, rs)

    assert r.status_code == 200
    refusal = r.text[r.text.index('id="picker-refusal"') :]
    assert "already assigned" in refusal
    assert "Shared Spec" in refusal
    assert await session.scalar(select(func.count()).select_from(InfoItemRepSpec)) == 1


@pytest.mark.asyncio
async def test_assign_refuses_an_unwritable_provider_server_side(client, session):
    """The disabled button is a template gate; a direct POST must not bypass it (#167)."""
    item = _make_item("Unwritable Assign Picker", rep_fields={})
    rs = _make_rep_spec("Drive Spec")
    rs.provider = "gdrive"
    session.add_all([item, rs])
    await session.flush()

    r = await _assign(client, item, rs)

    assert r.status_code == 200
    refusal = r.text[r.text.index('id="picker-refusal"') :]
    assert "Replicator has no Google Drive writer yet" in refusal
    assert await session.scalar(select(func.count()).select_from(InfoItemRepSpec)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("rep_spec_id", ["not-a-ulid", str(ULID())])
async def test_assign_refuses_a_spec_that_does_not_exist_inline(client, session, rep_spec_id):
    item = _make_item("Ghost Picker")
    session.add(item)
    await session.flush()

    r = await _assign(client, item, rep_spec_id)

    assert r.status_code == 200
    assert "no longer exists" in r.text[r.text.index('id="picker-refusal"') :]


@pytest.mark.asyncio
async def test_assign_on_an_unknown_item_is_404(client):
    r = await client.post(
        f"/dashboard/info-items/{ULID()}/rep-spec-picker/assign",
        data={"rep_spec_id": str(ULID())},
        headers=_HEADERS,
    )

    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_the_full_page_assign_route_is_retired(client, session):
    item = _make_item("Retired Assign Item")
    rs = _make_rep_spec()
    session.add_all([item, rs])
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/assign-rep-spec",
        data={"rep_spec_id": str(rs.rep_spec_id)},
        headers=_HEADERS,
    )

    assert r.status_code in (404, 405)
    assert await session.scalar(select(func.count()).select_from(InfoItemRepSpec)) == 0


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

    # Split on the <table> tag, not on the label alone: since archiver#182 the
    # scroll region wrapping the table carries the same accessible name, so the
    # bare string matches twice and the first slice holds no <tbody> at all.
    tag = '<table class="data-table" aria-label="Active Replication Spec assignments"'
    head, body = r.text.split(tag)[1].split("</table>")[0].split("<tbody>")
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
    # The whole section re-renders, matching the Deactivate beside it, so the
    # swap can move focus off the button it destroys (CR #37).
    assert 'id="ii-rep-spec-assignments"' in r.text
    assert 'getElementById("ii-rep-spec-heading")' in r.text
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
    # An irreversible action confirms itself; silence used to be the success
    # signal and a toast the failure one, which is backwards (CR #42).
    assert read_flash(r)["showFlash"]["level"] == "success"


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
    assert read_flash(r)["showFlash"]["level"] == "warning"
    assert "blob_absent" in read_flash(r)["showFlash"]["body"]


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

    # 200, not 422: a 4xx is discarded by htmx (docs/UI.md), so the refusal
    # would reach the operator as nothing at all (CR #36).
    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "error"
    assert "not been captured yet" in read_flash(r)["showFlash"]["body"]


@pytest.mark.asyncio
async def test_an_unregistered_refusal_still_reaches_the_operator(client, session, monkeypatch):
    """The refusal vocabulary and the exceptions it keys on now live in one
    module (CR #34), but a subclass can still be added without an entry — and a
    bare dict subscript inside the except block would 500 (CR #28)."""
    item, assignment, _ = await _assigned(
        session, name="Unregistered Item", url="https://example.com/unregistered"
    )

    async def _raise(*_args, **_kwargs):
        raise ManualIssuanceError(assignment.id, "a refusal nobody registered")

    monkeypatch.setattr("src.dashboard.routes.info_items.issue_for_assignment", _raise)

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/replicate",
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert "This replication could not be issued" in read_flash(r)["showFlash"]["body"]


@pytest.mark.asyncio
async def test_the_replicate_button_disables_itself_in_flight(client, session):
    """htmx does not deduplicate concurrent requests from an element, and this
    one writes into a permanent store — archive.org cannot be deleted at all, so
    a double-click is not a free retry (CR #29)."""
    item, _, _ = await _assigned(session, name="Debounce Item", url="https://example.com/debounce")

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    replicate_button = r.text.split("Replicate now")[0].rsplit("<button", 1)[1]
    assert 'hx-disabled-elt="this"' in replicate_button
    assert 'hx-target="#ii-rep-spec-assignments"' in replicate_button


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
        data={"rep_fields": '{"org": {"title": "WA LCB"}}'},
    )
    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["body"] == "Rep Fields saved."

    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "WA LCB"}}


async def _item_assigned_to(session, bag: dict, rs: RepSpec) -> InfoItem:
    item = _make_item("Assigned Bag Item", rep_fields=bag)
    session.add_all([item, rs])
    await session.flush()
    session.add(
        InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=rs.rep_spec_id,
            activated_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return item


_ORG_PATH = "organizations/{org.title_slug}/{source_revision.id}.html"


@pytest.mark.asyncio
async def test_rep_fields_save_refuses_a_bag_off_the_v1_shape(client, session):
    """Was "Saved." for anything that parsed as a JSON object (archiver#302)."""
    item = _make_item("Flat Bag Item")
    session.add(item)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data={"rep_fields": '{"key1": "value1"}'},
    )
    assert r.status_code == 422
    assert "key1" in r.text
    await session.refresh(item)
    assert item.rep_fields == {}


@pytest.mark.asyncio
async def test_rep_fields_save_refusal_names_the_assignment_and_key(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "WA LCB"}}, rs)

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data={"rep_fields": "{}"},
    )
    assert r.status_code == 422
    assert "Org Layout" in r.text
    assert "org.title_slug" in r.text
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_rep_fields_save_refuses_an_unrenderable_value(client, session):
    rs = _rep_spec_requiring(
        "Raw Name", "org.name", path_template="a/{org.name}/{source_revision.id}"
    )
    item = await _item_assigned_to(session, {"org": {"name": "wa_lcb"}}, rs)

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data={"rep_fields": '{"org": {"name": "WA LCB"}}'},
    )
    assert r.status_code == 422
    assert "Raw Name" in r.text
    assert "org.name" in r.text


@pytest.mark.asyncio
async def test_rep_fields_save_that_moves_a_destination_asks_first(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Old Name"}}, rs)

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data={"rep_fields": '{"org": {"title": "New Name"}}'},
    )
    assert r.status_code == 409
    assert "Org Layout" in r.text
    assert "organizations/old_name/" in r.text
    assert "organizations/new_name/" in r.text
    # The probe's placeholder revision id is in both paths; say so (CR 3).
    assert "example revision" in r.text
    # The confirmation re-sends exactly the bag it warned about, not whatever
    # the textarea holds by the time the operator clicks.
    assert "allow_destination_change" in r.text
    assert "New Name" in r.text
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "Old Name"}}


@pytest.mark.asyncio
async def test_rep_fields_save_moves_a_destination_when_confirmed(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Old Name"}}, rs)

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data={"rep_fields": '{"org": {"title": "New Name"}}', "allow_destination_change": "true"},
    )
    assert r.status_code == 200
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "New Name"}}


@pytest.mark.asyncio
async def test_rep_fields_save_invalid_json_is_422(client, session):
    item = _make_item("Bad JSON Item")
    session.add(item)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data={"rep_fields": "{not json"},
    )
    assert r.status_code == 422
    assert "Invalid" in r.text


@pytest.mark.asyncio
async def test_rep_fields_flash_fragments_add_no_nested_live_region(client, session):
    """The target is the live region (UI.md); an alert inside it can announce twice."""
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Old Name"}}, rs)
    url = f"/dashboard/info-items/{item.info_item_id}/rep-fields"

    refused = await client.patch(url, headers=_HEADERS, data={"rep_fields": "{}"})
    moved = await client.patch(
        url, headers=_HEADERS, data={"rep_fields": '{"org": {"title": "New Name"}}'}
    )
    for r in (refused, moved):
        assert 'role="alert"' not in r.text
        assert "aria-live" not in r.text


@pytest.mark.asyncio
async def test_create_refuses_a_bag_off_the_v1_shape(client, session):
    r = await client.post(
        _NEW_URL,
        data={"name": "Flat Created Item", "rep_fields": '{"key1": "value1"}'},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 422
    assert "key1" in r.text
    result = await session.execute(select(InfoItem).where(InfoItem.name == "Flat Created Item"))
    assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# The Replication section's Fields block  (archiver#307)
# ---------------------------------------------------------------------------
#
# One row per raw key the assigned specs require, each with its live derived
# slug and where the value comes from; stored keys no spec requires under
# "Other fields"; the JSON textarea kept inside a <details>. Both forms save
# through set_rep_fields (#302). The block is its own swap target, re-fetched on
# `replicationChanged` from its siblings and never by the assignments poll.


def _fields_block(html: str) -> str:
    """The Fields block alone, from its root to the details that close it."""
    start = html.index('id="ii-rep-fields"')
    return html[start : html.index("<!-- /ii-rep-fields -->", start)]


def _fields_form(**fields) -> dict:
    """The structured form's body: parallel field_key/field_value/field_type lists."""
    return {
        "field_key": list(fields),
        "field_value": [v if isinstance(v, str) else json.dumps(v) for v in fields.values()],
        "field_type": ["string" if isinstance(v, str) else "json" for v in fields.values()],
    }


def _dotted(**fields) -> dict:
    """``org__title="x"`` -> ``{"org.title": "x"}``: a keyword cannot hold a dot."""
    return {k.replace("__", "."): v for k, v in fields.items()}


@pytest.mark.asyncio
async def test_the_section_is_replication_and_keeps_its_anchor(client, session):
    """The section's deep link (archiver#301's redirect anchor, kept after #308 retired it)."""
    item = _make_item("Hub Replication Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert '<section id="replication" aria-label="Replication"' in r.text
    assert "Replicator" not in r.text


@pytest.mark.asyncio
async def test_the_fields_block_has_a_row_per_required_raw_key(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "WSLCB - Board"}}, rs)

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    block = _fields_block(r.text)
    assert 'id="ii-rep-fields-heading"' in block
    assert 'name="field_key" value="org.title"' in block
    assert 'value="WSLCB - Board"' in block
    assert "Org Layout" in block
    # The derived slug, through effective_rep_fields, and its source.
    assert "org.title_slug" in block
    assert "wslcb-board" in block
    assert "stored" in block


@pytest.mark.asyncio
async def test_a_missing_required_key_says_so(client, session):
    rs = _rep_spec_requiring(
        "Name Layout", "info_item.name", path_template="n/{info_item.name}/{source_revision.id}"
    )
    item = await _item_assigned_to(session, {"org": {"title": "Board"}}, rs)

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}/rep-fields", headers=_HEADERS)

    assert r.status_code == 200
    assert 'name="field_key" value="info_item.name"' in r.text
    assert "missing" in r.text
    # Stored but required by nothing: an Other field, removable.
    assert 'name="field_key" value="org.title"' in r.text
    assert "Other fields" in r.text
    assert "Remove" in r.text


@pytest.mark.asyncio
async def test_a_value_that_slugs_to_nothing_reads_as_such_not_missing(client, session):
    """archiver#312: its own state, in the gate's wording."""
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "!!!"}}, rs)

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}/rep-fields", headers=_HEADERS)

    assert "slugs to nothing" in r.text
    assert "org.title &#34;!!!&#34; slugs to nothing (org.title_slug)" in r.text


@pytest.mark.asyncio
async def test_a_stored_slug_reads_as_an_override(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Board", "title_slug": "custom"}}, rs)

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}/rep-fields", headers=_HEADERS)

    assert "override" in r.text
    assert 'name="field_key" value="org.title_slug"' in r.text


@pytest.mark.asyncio
async def test_an_item_with_a_composite_override_can_still_be_saved(client, session):
    """CR 1: the override's input was rendered on both raw rows, so the form
    posted its key twice and every structured save was refused."""
    rs = _rep_spec_requiring(
        "Short Layout",
        "org.acronym_or_title_slug",
        path_template="o/{org.acronym_or_title_slug}/{source_revision.id}",
    )
    bag = {"org": {"acronym": "A", "title": "T", "acronym_or_title_slug": "x"}}
    item = await _item_assigned_to(session, bag, rs)

    page = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields", headers=_HEADERS
    )
    assert page.text.count('name="field_key" value="org.acronym_or_title_slug"') == 1

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data=_fields_form(**{f"org.{k}": v for k, v in bag["org"].items()}),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_the_name_row_offers_the_item_name_without_its_acronym(client, session):
    rs = _rep_spec_requiring(
        "Name Layout", "info_item.name", path_template="n/{info_item.name}/{source_revision.id}"
    )
    item = await _item_assigned_to(session, {}, rs)
    item.name = "WSLCB - Meeting Schedule"
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}/rep-fields", headers=_HEADERS)

    assert 'data-suggestion="Meeting Schedule"' in r.text
    assert 'data-target="rf-input-info_item-name"' in r.text
    # Data stays in data attributes; the Alpine expression is a constant (CR 3).
    assert '@click="useSuggestion($el.dataset.target, $el.dataset.suggestion)"' in r.text


@pytest.mark.asyncio
async def test_an_item_with_no_assignments_has_no_required_rows(client, session):
    item = _make_item("Unassigned Fields Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}/rep-fields", headers=_HEADERS)

    assert r.status_code == 200
    assert "No assigned Replication Spec requires any fields." in r.text


@pytest.mark.asyncio
async def test_the_block_refetches_on_a_siblings_replication_change_only(client, session):
    """The coordination pattern: siblings fire it, this block listens - but not
    to its own save, which already swapped it."""
    item = _make_item("Listening Fields Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    block = _fields_block(r.text)
    root = block[: block.index(">")]
    assert f'hx-get="/dashboard/info-items/{item.info_item_id}/rep-fields"' in root
    assert "replicationChanged[detail.source!=='fields'] from:body" in root
    assert 'hx-swap="outerHTML"' in root


@pytest.mark.asyncio
async def test_a_refetch_never_moves_focus(client, session):
    item = _make_item("Refetch Focus Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}/rep-fields", headers=_HEADERS)

    assert r.status_code == 200
    assert 'getElementById("ii-rep-fields-heading")' not in r.text


@pytest.mark.asyncio
async def test_the_fields_form_routes_refusals_into_its_flash(client, session):
    """Without hx-target-4xx a 422 never reaches the operator (archiver#302)."""
    item = _make_item("Fields Flash Item")
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    block = _fields_block(r.text)
    for form_start in ('id="ii-rep-fields-form"', 'id="ii-rep-fields-json-form"'):
        form = block[block.index(form_start) :]
        form = form[: form.index(">")]
        assert f'hx-patch="/dashboard/info-items/{item.info_item_id}/rep-fields"' in form
        assert 'hx-target="#rep-fields-flash"' in form
        assert 'hx-target-422="#rep-fields-flash"' in form
        assert 'hx-target-409="#rep-fields-flash"' in form
    assert 'id="rep-fields-flash" aria-live="polite" aria-atomic="true"' in block


@pytest.mark.asyncio
async def test_edit_as_json_survives_inside_a_details(client, session):
    item = _make_item("JSON Details Item", rep_fields={"org": {"title": "Board"}})
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    block = _fields_block(r.text)
    details = block[block.index("<details") :]
    assert "Edit as JSON" in details
    assert 'name="rep_fields"' in details
    assert "&#34;title&#34;: &#34;Board&#34;" in details


@pytest.mark.asyncio
async def test_a_structured_save_stores_the_bag_and_swaps_the_block(client, session):
    item = _make_item("Structured Save Item")
    session.add(item)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data=_fields_form(**_dotted(org__title="WA LCB", meta__year=2024)),
    )

    assert r.status_code == 200
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "WA LCB"}, "meta": {"year": 2024}}
    # The form targets the flash; success re-targets the whole block, which
    # now reads from the stored bag.
    assert r.headers["HX-Retarget"] == "#ii-rep-fields"
    assert r.headers["HX-Reswap"] == "outerHTML"
    assert 'id="ii-rep-fields"' in r.text
    assert 'getElementById("ii-rep-fields-heading")' in r.text


class _RenderedForm(HTMLParser):
    """The Fields form's inputs in document order, as the browser would post them."""

    def __init__(self) -> None:
        super().__init__()
        self.body: dict[str, list[str]] = {"field_key": [], "field_value": [], "field_type": []}
        self._in_form = self._in_template = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id") == "ii-rep-fields-form":
            self._in_form = True
        elif tag == "template":
            self._in_template = True
        elif self._in_form and not self._in_template and a.get("name") in self.body:
            self.body[a["name"]].append(a.get("value") or "")

    def handle_endtag(self, tag):
        if tag == "template":
            self._in_template = False
        elif tag == "form":
            self._in_form = False


@pytest.mark.asyncio
async def test_saving_the_form_unedited_leaves_the_bag_unchanged(client, session):
    """CR 5: a stored null or "" rendered blank, and blank means "not set", so a
    no-op save deleted them."""
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    bag = {
        "org": {"title": "Board", "title_slug": "custom", "note": ""},
        "meta": {"year": 2024, "draft": False, "gone": None},
    }
    item = await _item_assigned_to(session, bag, rs)
    url = f"/dashboard/info-items/{item.info_item_id}/rep-fields"

    page = await client.get(url, headers=_HEADERS)
    form = _RenderedForm()
    form.feed(page.text)
    r = await client.patch(url, headers=_HEADERS, data=form.body)

    assert r.status_code == 200
    await session.refresh(item)
    assert item.rep_fields == bag


@pytest.mark.asyncio
async def test_the_blocks_own_renders_carry_no_out_of_band_swap(client, session):
    """CR 8. The status cell is shared with the readout, which marks it
    hx-swap-oob. Leaked into the block, the save's outerHTML swap would pull
    every status cell out of the response and swap it in by id instead."""
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Board"}}, rs)
    url = f"/dashboard/info-items/{item.info_item_id}/rep-fields"

    page = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    refetch = await client.get(url, headers=_HEADERS)
    saved = await client.patch(
        url, headers=_HEADERS, data=_fields_form(**_dotted(org__title="Board"))
    )

    for r in (page, refetch, saved):
        assert r.status_code == 200
        assert 'id="rf-status-org-title"' in r.text
        assert "hx-swap-oob" not in r.text


@pytest.mark.asyncio
async def test_a_save_fires_replication_changed_and_confirms(client, session):
    item = _make_item("Save Trigger Item")
    session.add(item)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data=_fields_form(**_dotted(org__title="WA LCB")),
    )

    triggers = read_flash(r)
    assert triggers["replicationChanged"] == {"source": "fields"}
    assert triggers["showFlash"]["level"] == "success"


@pytest.mark.asyncio
async def test_a_structured_save_drops_blank_values(client, session):
    item = _make_item("Blank Drop Item", rep_fields={"org": {"title": "Board"}})
    session.add(item)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data=_fields_form(**_dotted(org__title="")),
    )

    assert r.status_code == 200
    await session.refresh(item)
    assert item.rep_fields == {}


@pytest.mark.asyncio
async def test_a_structured_refusal_names_the_assignment_and_key(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "WA LCB"}}, rs)

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data=_fields_form(**_dotted(org__title="")),
    )

    assert r.status_code == 422
    assert "Org Layout" in r.text
    assert "org.title_slug" in r.text
    # A refusal stays in the flash: the operator's input is still on screen.
    assert "HX-Retarget" not in r.headers
    assert "HX-Trigger" not in r.headers
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_a_form_that_cannot_build_a_bag_is_refused_by_name(client, session):
    item = _make_item("Unbuildable Item")
    session.add(item)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data={
            "field_key": ["meta.year", "meta.year"],
            "field_value": ["2024", "2025"],
            "field_type": ["json", "json"],
        },
    )

    assert r.status_code == 422
    assert "meta.year appears twice" in r.text


@pytest.mark.asyncio
async def test_a_structured_move_asks_first_and_confirms_with_that_bag(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Old Name"}}, rs)

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        headers=_HEADERS,
        data=_fields_form(**_dotted(org__title="New Name")),
    )

    assert r.status_code == 409
    assert "organizations/new_name/" in r.text
    # Save and move re-sends the bag that was warned about, as JSON.
    assert "allow_destination_change" in r.text
    assert "New Name" in r.text


@pytest.mark.parametrize(
    "bag",
    [
        {"org": {"title": "WA LCB"}, "meta": {"year": 2024, "draft": False}},
        {"org": {"title": "WA LCB", "title_slug": "custom"}},
    ],
)
@pytest.mark.asyncio
async def test_the_json_path_and_the_structured_path_store_the_same_bag(client, session, bag):
    """Two forms, one gate: "Edit as JSON" is not a way around set_rep_fields."""
    stored = []
    for body in (
        {"rep_fields": json.dumps(bag)},
        _fields_form(**{f"{ns}.{k}": v for ns, fields in bag.items() for k, v in fields.items()}),
    ):
        item = _make_item("Parity Item")
        session.add(item)
        await session.flush()
        r = await client.patch(
            f"/dashboard/info-items/{item.info_item_id}/rep-fields", headers=_HEADERS, data=body
        )
        assert r.status_code == 200
        assert r.headers["HX-Retarget"] == "#ii-rep-fields"
        await session.refresh(item)
        stored.append(item.rep_fields)

    assert stored == [bag, bag]


@pytest.mark.asyncio
async def test_the_json_path_refuses_what_the_structured_path_refuses(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "WA LCB"}}, rs)
    url = f"/dashboard/info-items/{item.info_item_id}/rep-fields"

    as_json = await client.patch(url, headers=_HEADERS, data={"rep_fields": "{}"})
    structured = await client.patch(url, headers=_HEADERS, data=_fields_form())

    assert as_json.status_code == structured.status_code == 422
    assert as_json.text == structured.text


@pytest.mark.asyncio
async def test_the_readout_reslugs_unsaved_input_out_of_band(client, session):
    """The live slug: rendered by the server, through effective_rep_fields."""
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Board"}}, rs)

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields/readout",
        headers=_HEADERS,
        params=_fields_form(**_dotted(org__title="New Name")),
    )

    assert r.status_code == 200
    assert 'id="rf-status-org-title" hx-swap-oob="true"' in r.text
    assert "new_name" in r.text
    assert "HX-Trigger" not in r.headers
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "Board"}}


@pytest.mark.asyncio
async def test_the_readout_shows_an_empty_slug_as_it_is_typed(client, session):
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Board"}}, rs)

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields/readout",
        headers=_HEADERS,
        params=_fields_form(**_dotted(org__title="!!!")),
    )

    assert "slugs to nothing" in r.text


@pytest.mark.asyncio
async def test_the_readout_tolerates_input_the_save_would_refuse(client, session):
    """Half-typed input is the readout's normal case; it reads what it can."""
    rs = _rep_spec_requiring("Org Layout", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Board"}}, rs)

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields/readout",
        headers=_HEADERS,
        params={
            "field_key": ["org.title", "org.title"],
            "field_value": ["A", "B"],
            "field_type": ["string", "string"],
        },
    )

    assert r.status_code == 200
    assert 'id="rf-status-org-title"' in r.text


@pytest.mark.asyncio
async def test_deactivate_fires_replication_changed(client, session):
    """The Fields rows come from the active assignments, so a deactivate changes them."""
    item, assignment, _revision = await _assigned(
        session, name="Deact Trigger", url="https://example.com/deact-trigger"
    )

    r = await client.delete(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}",
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert read_flash(r)["replicationChanged"] == {"source": "assignments"}


@pytest.mark.asyncio
async def test_replicate_now_leaves_the_fields_block_alone(client, session):
    """It changes nothing a sibling renders, and a refetch would discard any
    unsaved input in the Fields block."""
    item, assignment, _revision = await _assigned(
        session, name="Replicate Quiet", url="https://example.com/replicate-quiet"
    )

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/replicate",
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert "showFlash" in read_flash(r)
    assert "replicationChanged" not in read_flash(r)


@pytest.mark.asyncio
async def test_the_assignments_poll_never_touches_the_fields_block(client, session):
    """The poll swaps its own wrapper, carries no Fields markup and fires nothing."""
    item, assignment, revision = await _assigned(
        session, name="Poll Leaves Fields", url="https://example.com/poll-leaves-fields"
    )
    session.add(_command_for(assignment, revision, state="requested", issued_at=datetime.now(UTC)))
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    assert r.status_code == 200
    assert 'hx-trigger="every 2s"' in r.text
    assert "ii-rep-fields" not in r.text
    assert "HX-Trigger" not in r.headers


@pytest.mark.asyncio
async def test_the_fields_block_sits_outside_the_polled_wrapper(client, session):
    item, assignment, revision = await _assigned(
        session, name="Fields Outside Poll", url="https://example.com/fields-outside-poll"
    )
    session.add(_command_for(assignment, revision, state="requested", issued_at=datetime.now(UTC)))
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    section = r.text[r.text.index('id="ii-rep-spec-assignments"') :]
    assert section.index("<!-- /ii-rep-spec-assignments -->") < section.index('id="ii-rep-fields"')


# --- The spec selected in the picker joins the rows (archiver#308) ---


@pytest.mark.asyncio
async def test_a_selected_spec_adds_its_keys_to_the_fields_block(client, session):
    item = _make_item("Selecting Item", rep_fields={})
    rs = _rep_spec_requiring("Picked Spec", "org.title_slug", path_template=_ORG_PATH)
    session.add_all([item, rs])
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        params={"selected_spec": str(rs.rep_spec_id)},
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert 'name="field_key" value="org.title"' in r.text
    assert "Required by Picked Spec" in r.text
    assert "missing" in r.text
    # CR 6: the rows are no longer only the assigned specs'.
    assert 'aria-label="Fields the Replication Specs require"' in r.text
    assert "Picked Spec" in r.text[: r.text.index("<form")]


@pytest.mark.asyncio
async def test_the_selection_survives_the_blocks_own_refetch_and_save(client, session):
    item = _make_item("Sticky Selection Item", rep_fields={})
    rs = _rep_spec_requiring("Sticky Spec", "org.title_slug", path_template=_ORG_PATH)
    session.add_all([item, rs])
    await session.flush()
    url = f"/dashboard/info-items/{item.info_item_id}/rep-fields"

    r = await client.get(url, params={"selected_spec": str(rs.rep_spec_id)}, headers=_HEADERS)

    root = r.text[: r.text.index(">")]
    assert f'hx-get="{url}?selected_spec={rs.rep_spec_id}"' in root
    hidden = f'<input type="hidden" name="selected_spec" value="{rs.rep_spec_id}">'
    assert r.text.count(hidden) == 2  # the row form and the JSON form

    r = await client.patch(
        url,
        data={**_fields_form(**_dotted(org__title="WSLCB")), "selected_spec": str(rs.rep_spec_id)},
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert "Required by Sticky Spec" in r.text
    assert hidden in r.text


@pytest.mark.asyncio
async def test_selecting_focuses_the_first_key_the_spec_still_needs(client, session):
    item = _make_item("Focus Selection Item", rep_fields={"org": {"title": "WSLCB"}})
    rs = _rep_spec_requiring(
        "Focus Spec",
        "org.title_slug",
        "info_item.name",
        path_template="o/{org.title_slug}/{info_item.name}/{source_revision.id}.html",
    )
    session.add_all([item, rs])
    await session.flush()
    url = f"/dashboard/info-items/{item.info_item_id}/rep-fields"

    r = await client.get(
        url, params={"selected_spec": str(rs.rep_spec_id), "focus": "true"}, headers=_HEADERS
    )

    assert 'getElementById("rf-input-info_item-name")' in r.text
    assert 'getElementById("ii-rep-fields-heading")' not in r.text

    r = await client.get(url, params={"selected_spec": str(rs.rep_spec_id)}, headers=_HEADERS)

    assert 'getElementById("rf-input-' not in r.text


@pytest.mark.asyncio
async def test_the_focus_target_is_written_as_a_js_string(client, session):
    """CR 11. Keys come from operator-authored required_fields, and HTML
    escaping is the wrong context inside <script>: entities are not decoded."""
    item = _make_item("Script Context Item", rep_fields={})
    rs = _rep_spec_requiring("Odd Key", 'info_item.a"b', path_template="x/{source_revision.id}")
    session.add_all([item, rs])
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        params={"selected_spec": str(rs.rep_spec_id), "focus": "true"},
        headers=_HEADERS,
    )

    assert 'getElementById("rf-input-info_item-a\\"b")' in r.text


@pytest.mark.asyncio
async def test_selecting_focuses_by_the_specs_keys_not_its_name(client, session):
    """CR 4. RepSpec names are not unique: focus by name could land on a row
    only an assigned namesake needs."""
    assigned = _rep_spec_requiring("Same Name", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {}, assigned)
    picked = _rep_spec_requiring(
        "Same Name", "info_item.name", path_template="x/{info_item.name}/{source_revision.id}"
    )
    session.add(picked)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        params={"selected_spec": str(picked.rep_spec_id), "focus": "true"},
        headers=_HEADERS,
    )

    assert 'getElementById("rf-input-info_item-name")' in r.text
    assert 'getElementById("rf-input-org-title")' not in r.text


@pytest.mark.asyncio
async def test_a_selected_spec_already_assigned_adds_nothing(client, session):
    rs = _rep_spec_requiring("Assigned Pick", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {}, rs)

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        params={"selected_spec": str(rs.rep_spec_id)},
        headers=_HEADERS,
    )

    assert r.text.count('name="field_key" value="org.title"') == 1
    assert 'name="selected_spec"' not in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", ["not-a-ulid", str(ULID())])
async def test_an_unknown_selection_is_ignored(client, session, selected):
    item = _make_item("Unknown Selection Item")
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        params={"selected_spec": selected},
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert "No assigned Replication Spec requires any fields." in r.text


@pytest.mark.asyncio
async def test_the_selection_can_be_cleared(client, session):
    item = _make_item("Clear Selection Item", rep_fields={})
    rs = _rep_spec_requiring("Clear Spec", "org.title_slug", path_template=_ORG_PATH)
    session.add_all([item, rs])
    await session.flush()
    url = f"/dashboard/info-items/{item.info_item_id}/rep-fields"

    r = await client.get(url, params={"selected_spec": str(rs.rep_spec_id)}, headers=_HEADERS)

    clear = r.text[: r.text.index(">Clear<")]
    clear = clear[clear.rindex("<button") :]
    assert f'hx-get="{url}"' in clear
    assert 'hx-target="#ii-rep-fields"' in clear


@pytest.mark.asyncio
async def test_the_readout_covers_the_selected_spec(client, session):
    item = _make_item("Readout Selection Item", rep_fields={})
    rs = _rep_spec_requiring("Readout Spec", "org.title_slug", path_template=_ORG_PATH)
    session.add_all([item, rs])
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields/readout",
        params={
            **_fields_form(**_dotted(org__title="WSLCB")),
            "selected_spec": str(rs.rep_spec_id),
        },
        headers=_HEADERS,
    )

    assert 'id="rf-status-org-title"' in r.text
    assert "wslcb" in r.text


@pytest.mark.asyncio
async def test_save_and_move_keeps_the_selection(client, session):
    rs = _rep_spec_requiring("Moving Spec", "org.title_slug", path_template=_ORG_PATH)
    item = await _item_assigned_to(session, {"org": {"title": "Old"}}, rs)
    picked = _rep_spec_requiring("Picked Too", "info_item.name", path_template="x/{info_item.name}")
    session.add(picked)
    await session.flush()

    r = await client.patch(
        f"/dashboard/info-items/{item.info_item_id}/rep-fields",
        data={
            **_fields_form(**_dotted(org__title="New")),
            "selected_spec": str(picked.rep_spec_id),
        },
        headers=_HEADERS,
    )

    assert r.status_code == 409
    assert f'"selected_spec": "{picked.rep_spec_id}"' in r.text


# --- The assignments table listens too (archiver#308) ---


@pytest.mark.asyncio
async def test_the_assignments_table_refetches_on_a_siblings_replication_change(client, session):
    """The picker's assign adds a row; deactivate's own swap already shows its change."""
    item, _assignment, _revision = await _assigned(
        session, name="Table Listens", url="https://example.com/table-listens"
    )

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    listener = r.text[r.text.rindex("<div", 0, r.text.index("replicationChanged[")) :]
    listener = listener[: listener.index(">")]
    assert "replicationChanged[detail.source!=='assignments'] from:body" in listener
    assert f'hx-get="/dashboard/info-items/{item.info_item_id}/rep-spec-assignments"' in listener
    assert 'hx-target="#ii-rep-spec-assignments"' in listener
    assert 'hx-sync="closest #ii-rep-spec-assignments:drop"' in listener


@pytest.mark.asyncio
async def test_the_rep_fields_suggestion_route_is_retired(client, session):
    item = _make_item("Retired Suggest Item")
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/suggest-rep-fields", headers=_HEADERS
    )

    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{item_id}/rep-spec-assignments  (archiver#212)
# ---------------------------------------------------------------------------
#
# Issuance and closure are separated by a bus round trip: the POST swap renders
# at ~50ms and the writeback lands the terminal state ~800ms later, so the
# section the operator was left looking at said `requested` until they refreshed
# by hand. This is the second render.


@pytest.mark.asyncio
async def test_the_assignments_section_is_served_as_a_standalone_fragment(client, session):
    item, _assignment, _revision = await _assigned(
        session, name="Poll Fragment", url="https://example.com/poll-fragment"
    )

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    assert r.status_code == 200
    assert 'id="ii-rep-spec-assignments"' in r.text


@pytest.mark.asyncio
async def test_a_poll_render_never_moves_focus(client, session):
    """``swapped`` is what runs the focus script. A poll firing every two
    seconds would drag a keyboard user back to the heading on each tick, which
    is worse than the stale value it fixes (archiver#171 CR #37)."""
    item, _assignment, _revision = await _assigned(
        session, name="Poll Focus", url="https://example.com/poll-focus"
    )

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    # Asserted before the absence check below, which a 404 would satisfy too.
    assert r.status_code == 200
    assert 'getElementById("ii-rep-spec-heading")' not in r.text


@pytest.mark.asyncio
async def test_the_section_polls_while_a_command_is_open(client, session):
    item, assignment, revision = await _assigned(
        session, name="Poll Open", url="https://example.com/poll-open"
    )
    session.add(_command_for(assignment, revision, state="requested", issued_at=datetime.now(UTC)))
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    assert f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments" in r.text
    assert 'hx-trigger="every 2s"' in r.text


@pytest.mark.asyncio
async def test_the_swap_that_lands_a_terminal_state_is_the_one_that_stops_polling(client, session):
    """Self-terminating by construction: the attributes are rendered from the
    same rows the badge is, so no tick has to decide to be the last one."""
    item, assignment, revision = await _assigned(
        session, name="Poll Done", url="https://example.com/poll-done"
    )
    session.add(
        _command_for(
            assignment,
            revision,
            state="complete",
            issued_at=datetime.now(UTC),
            closed_at=datetime.now(UTC),
        )
    )
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    assert r.status_code == 200
    assert "every 2s" not in r.text
    assert "complete" in r.text


@pytest.mark.asyncio
async def test_polling_stops_when_an_open_command_outruns_the_window(client, session):
    """The reaper's horizon is six hours; polling to it would leave an idle tab
    asking every two seconds all afternoon."""
    item, assignment, revision = await _assigned(
        session, name="Poll Stalled", url="https://example.com/poll-stalled"
    )
    session.add(
        _command_for(
            assignment,
            revision,
            state="requested",
            issued_at=datetime(2026, 5, 3, tzinfo=UTC),
        )
    )
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    assert r.status_code == 200
    assert "every 2s" not in r.text
    assert "still open" in r.text.lower()


@pytest.mark.asyncio
async def test_replicate_now_hands_back_a_section_that_polls(client, session):
    """The POST's own render starts the wait, so the operator never has to act
    twice to see the outcome."""
    item, assignment, _revision = await _assigned(
        session, name="Poll After Post", url="https://example.com/poll-after-post"
    )

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments/{assignment.id}/replicate",
        headers=_HEADERS,
    )

    assert r.status_code == 200
    assert 'hx-trigger="every 2s"' in r.text


@pytest.mark.asyncio
async def test_the_full_detail_page_starts_watching_an_already_open_command(client, session):
    """CR 12. The swap routes are not the only way this section reaches a
    browser: a reload, or arriving at the item from the list while a command is
    in flight, renders it through the detail page. Wired only to the swaps, that
    page was inert - the original defect, on the most ordinary path there is."""
    item, assignment, revision = await _assigned(
        session, name="Detail Poll", url="https://example.com/detail-poll"
    )
    session.add(_command_for(assignment, revision, state="requested", issued_at=datetime.now(UTC)))
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert f'hx-get="/dashboard/info-items/{item.info_item_id}/rep-spec-assignments"' in r.text
    assert 'hx-trigger="every 2s"' in r.text


@pytest.mark.asyncio
async def test_the_full_detail_page_does_not_poll_with_nothing_open(client, session):
    """The other half: a page that always polled would be worse than one that
    never did."""
    item, assignment, revision = await _assigned(
        session, name="Detail Idle", url="https://example.com/detail-idle"
    )
    session.add(
        _command_for(
            assignment,
            revision,
            state="complete",
            issued_at=datetime.now(UTC),
            closed_at=datetime.now(UTC),
        )
    )
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert 'hx-trigger="every 2s"' not in r.text


@pytest.mark.asyncio
async def test_the_poll_fragment_is_never_served_from_a_cache(client, session):
    """CR 15. A fragment fetched every two seconds is the one response here that
    must not come from a cache: a stale body would freeze the section on a state
    that looks authoritative, which is indistinguishable from the bug #212 fixes.
    GET is the cacheable method, so the header goes on the GET."""
    item, _assignment, _revision = await _assigned(
        session, name="Poll Cache", url="https://example.com/poll-cache"
    )

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    assert r.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_a_poll_always_yields_to_a_row_action(client, session):
    """archiver#220. The poll and both row actions swap one wrapper, so the
    response that lands second finds its target detached and is discarded.
    Unsynced, that was sometimes the operator's: no swap, no toast, no focus,
    and - if the poll had read before the commit - a section that stopped
    polling on pre-issuance state. The poll must always be the one that loses."""
    item, assignment, revision = await _assigned(
        session, name="Poll Yields", url="https://example.com/poll-yields"
    )
    session.add(_command_for(assignment, revision, state="requested", issued_at=datetime.now(UTC)))
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/rep-spec-assignments", headers=_HEADERS
    )

    assert r.status_code == 200
    assert poll_sync_violations(r.text, "ii-rep-spec-assignments") == []
