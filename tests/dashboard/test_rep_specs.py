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
