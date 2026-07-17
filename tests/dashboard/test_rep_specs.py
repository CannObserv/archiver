"""Tests for /dashboard/rep-specs/ routes."""

import json
from datetime import UTC, datetime

import pytest

from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    RepSpec,
)

_HEADERS = {"X-ExeDev-UserID": "ext-repspecs", "X-ExeDev-Email": "repspecs@example.com"}
_LIST_URL = "/dashboard/rep-specs/"
_NEW_URL = "/dashboard/rep-specs/new"

_GCS_DOC = {
    "provider": "gcs",
    "credentials_alias": "default",
    "path_template": "items/{info_item_id}.json",
    "required_fields": [],
}


def _make_rep_spec(name: str = "Test Spec", provider: str = "gcs") -> RepSpec:
    doc = {
        "provider": provider,
        "credentials_alias": "default",
        "path_template": "items/{info_item_id}.json",
        "required_fields": [],
    }
    return RepSpec(provider=provider, name=name, schema_version=1, document=doc)


# ---------------------------------------------------------------------------
# GET /dashboard/rep-specs/
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
async def test_list_shows_spec_name(client, session):
    spec = _make_rep_spec("Visible Spec")
    session.add(spec)
    await session.flush()

    r = await client.get(_LIST_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "Visible Spec" in r.text


@pytest.mark.asyncio
async def test_list_provider_filter(client, session):
    session.add(_make_rep_spec("GCS Spec", "gcs"))
    gdrive_doc = {
        "provider": "gdrive",
        "credentials_alias": "default",
        "path_template": "{info_item_id}",
        "required_fields": [],
    }
    session.add(
        RepSpec(provider="gdrive", name="GDrive Spec", schema_version=1, document=gdrive_doc)
    )
    await session.flush()

    r = await client.get(_LIST_URL + "?provider=gcs", headers=_HEADERS)
    assert r.status_code == 200
    assert "GCS Spec" in r.text
    assert "GDrive Spec" not in r.text


# ---------------------------------------------------------------------------
# GET /dashboard/rep-specs/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_unauthenticated_redirects(client, session):
    spec = _make_rep_spec("Detail Unauth")
    session.add(spec)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_detail_not_found_returns_404(client):
    from ulid import ULID

    r = await client.get(f"/dashboard/rep-specs/{ULID()}", headers=_HEADERS)
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_detail_shows_spec_info(client, session):
    spec = _make_rep_spec("Detail Spec")
    session.add(spec)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Detail Spec" in r.text
    assert "gcs" in r.text


@pytest.mark.asyncio
async def test_detail_shows_active_assignments(client, session):
    spec = _make_rep_spec("Assigned Spec")
    session.add(spec)
    await session.flush()

    item = InfoItem(name="Assigned Item")
    session.add(item)
    await session.flush()

    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(assignment)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "Assigned Item" in r.text


@pytest.mark.asyncio
async def test_detail_assignment_has_deactivate_button(client, session):
    """Assignments can be deactivated from the RepSpec screen too (#80), reusing
    the existing DELETE /info-items/{id}/rep-spec-assignments/{aid} endpoint."""
    spec = _make_rep_spec("Deactivatable Spec")
    session.add(spec)
    await session.flush()
    item = InfoItem(name="Assigned Item 2")
    session.add(item)
    await session.flush()
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(assignment)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert f'id="rs-assignment-{assignment.id}"' in r.text
    assert (
        f'hx-delete="/dashboard/info-items/{item.info_item_id}'
        f'/rep-spec-assignments/{assignment.id}"' in r.text
    )
    assert "Deactivate" in r.text


@pytest.mark.asyncio
async def test_detail_uses_entity_card_eyebrow(client, session):
    """RepSpec detail converges on entity-card + eyebrow; grid uses __item; id copyable (#80)."""
    spec = _make_rep_spec("Eyebrow Spec")
    session.add(spec)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'class="eyebrow">Replication Specification<' in r.text
    assert "entity-card__header" in r.text
    assert 'aria-label="Breadcrumb"' not in r.text
    assert 'id="rep-spec-heading"' in r.text
    # detail-grid uses __item wrappers, not bare <dl><dt><dd> (the misalignment bug).
    assert "<dt>" not in r.text
    assert "writeText(v)" in r.text


@pytest.mark.asyncio
async def test_detail_public_url_open_button(client, session):
    """A public_url writeback target opens via the shared 'Open ↗' button."""
    spec = _make_rep_spec("Public-URL Spec")
    session.add(spec)
    await session.flush()

    item = InfoItem(name="Public-URL Item")
    session.add(item)
    await session.flush()

    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
        public_url="https://cdn.example.com/items/thing.json",
    )
    session.add(assignment)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'href="https://cdn.example.com/items/thing.json"' in r.text
    assert ">Open ↗</a>" in r.text


@pytest.mark.asyncio
async def test_detail_non_http_public_url_gets_no_open_button(client, session):
    """A non-http(s) public_url (gs://, or a javascript: injection attempt) gets
    no clickable Open affordance — open_button guards the scheme (#78 CR7)."""
    spec = _make_rep_spec("Non-HTTP Spec")
    session.add(spec)
    await session.flush()

    item = InfoItem(name="Non-HTTP Item")
    session.add(item)
    await session.flush()

    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
        public_url="javascript:alert(document.cookie)",
    )
    session.add(assignment)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert ">Open ↗</a>" not in r.text
    assert 'href="javascript:' not in r.text


# ---------------------------------------------------------------------------
# GET /dashboard/rep-specs/new
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
    assert "provider" in r.text


# ---------------------------------------------------------------------------
# POST /dashboard/rep-specs/new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_unauthenticated_redirects(client):
    r = await client.post(
        _NEW_URL,
        data={"provider": "gcs", "name": "Test", "document": "{}"},
        follow_redirects=False,
    )
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_create_valid_spec_redirects_to_detail(client):
    r = await client.post(
        _NEW_URL,
        data={
            "provider": "gcs",
            "name": "Create Via Dashboard",
            "document": json.dumps(_GCS_DOC),
        },
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "/dashboard/rep-specs/" in r.headers["location"]


@pytest.mark.asyncio
async def test_create_invalid_json_rerenders_form(client):
    r = await client.post(
        _NEW_URL,
        data={"provider": "gcs", "name": "Bad", "document": "not-json"},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "error" in r.text.lower() or "invalid" in r.text.lower()
    assert "not-json" in r.text  # document_raw round-trips into server response


@pytest.mark.asyncio
async def test_create_invalid_schema_rerenders_form(client):
    r = await client.post(
        _NEW_URL,
        data={"provider": "gcs", "name": "Bad Schema", "document": json.dumps({"provider": "gcs"})},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "error" in r.text.lower() or "invalid" in r.text.lower()
    assert "Bad Schema" in r.text  # name round-trips into server response
