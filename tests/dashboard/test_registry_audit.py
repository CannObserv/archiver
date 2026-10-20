"""Tests for the Registry health badge, its list page and the detail notices (archiver#164).

A stored document the current schema rejects publishes fine and cannot be
re-saved. The badge makes the count visible from the home screen; the list page
names each one with its remedy; the detail notice tells the operator before an
edit is refused, not after.
"""

from datetime import UTC, datetime

import pytest
from markupsafe import escape
from sqlalchemy.exc import OperationalError

from src.core.models import InfoItem, InfoItemRepSpec, InfoSource, RepSpec
from src.dashboard.routes import index as index_routes

_HEADERS = {"X-ExeDev-UserID": "ext-registry", "X-ExeDev-Email": "registry@example.com"}


def _legacy_source() -> InfoSource:
    return InfoSource(
        url="https://example.com/registry-audit",
        source_specs=[
            {
                "target": {"url": "https://example.com/registry-audit"},
                "extraction": {"algorithm": "full_page"},
                "fingerprint": {},
                "schema_version": 1,
            }
        ],
    )


def _gcs_doc(**object_options) -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        "required_fields": ["info_item.slug"],
        "object_options": object_options or {"storage_class": "STANDARD"},
    }


# ---------------------------------------------------------------------------
# Badge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_loads_the_registry_badge(client):
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert 'hx-get="/dashboard/health/registry"' in r.text


@pytest.mark.asyncio
async def test_registry_badge_ok_when_every_document_validates(client, session):
    session.add(InfoItem(name="valid-registry"))
    await session.flush()

    r = await client.get("/dashboard/health/registry", headers=_HEADERS)

    assert r.status_code == 200
    assert "badge--success" in r.text
    assert ">ok<" in r.text
    assert "documents checked" in r.text


@pytest.mark.asyncio
async def test_registry_badge_counts_invalid_documents_and_links_the_list(client, session):
    session.add(_legacy_source())
    await session.flush()

    r = await client.get("/dashboard/health/registry", headers=_HEADERS)

    assert "badge--warning" in r.text
    assert "1 invalid" in r.text
    assert 'href="/dashboard/registry-audit"' in r.text
    # Named for a reader that meets it out of context, as the bus badges are
    # (archiver#271): "1 invalid" alone says nothing about where it goes.
    assert 'aria-label="Registry: 1 invalid - open Registry audit"' in r.text


@pytest.mark.asyncio
async def test_registry_badge_reports_a_database_failure(client, monkeypatch):
    async def _boom(_db):
        raise OperationalError("SELECT", {}, OSError("connection refused"))

    monkeypatch.setattr(index_routes, "audit_stored_documents", _boom)

    r = await client.get("/dashboard/health/registry", headers=_HEADERS)

    assert "badge--danger" in r.text
    assert "connection refused" in r.text


@pytest.mark.asyncio
async def test_registry_badge_leaves_a_sweep_bug_to_500(client, monkeypatch):
    """CR 5. A document a validator raises on is already a finding, so what
    reaches the handler is the database or a bug in the sweep - and a bug
    dressed as "error" would read as a database condition."""

    async def _boom(_db):
        raise TypeError("sweep bug, not a database state")

    monkeypatch.setattr(index_routes, "audit_stored_documents", _boom)

    with pytest.raises(TypeError):
        await client.get("/dashboard/health/registry", headers=_HEADERS)


@pytest.mark.asyncio
async def test_registry_badge_requires_auth(client):
    r = await client.get("/dashboard/health/registry", follow_redirects=False)
    assert r.status_code == 307


# ---------------------------------------------------------------------------
# List page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_page_names_each_finding_with_link_and_message(client, session):
    src = _legacy_source()
    session.add(src)
    await session.flush()

    r = await client.get("/dashboard/registry-audit", headers=_HEADERS)

    assert r.status_code == 200
    assert f'href="/dashboard/info-sources/{src.info_source_id}"' in r.text
    assert "Source spec" in r.text
    assert escape("'target' was unexpected") in r.text


@pytest.mark.asyncio
async def test_list_page_gives_a_frozen_rep_spec_the_clone_remedy(client, session):
    spec = RepSpec(
        provider="gcs", name="frozen-registry", schema_version=1, document=_gcs_doc(folder_id="x")
    )
    item = InfoItem(name="frozen-registry-item")
    session.add_all([spec, item])
    await session.flush()
    session.add(
        InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
            activated_at=datetime.now(UTC),
        )
    )
    await session.flush()

    r = await client.get("/dashboard/registry-audit", headers=_HEADERS)

    assert f'href="/dashboard/rep-specs/{spec.rep_spec_id}"' in r.text
    assert "clone" in r.text.lower()


@pytest.mark.asyncio
async def test_list_page_empty_state(client):
    r = await client.get("/dashboard/registry-audit", headers=_HEADERS)
    assert r.status_code == 200
    assert "Every stored document validates" in r.text


@pytest.mark.asyncio
async def test_list_page_requires_auth(client):
    r = await client.get("/dashboard/registry-audit", follow_redirects=False)
    assert r.status_code == 307


# ---------------------------------------------------------------------------
# Detail notices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_info_source_detail_notice(client, session):
    src = _legacy_source()
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)

    assert 'id="stored-document-notice"' in r.text
    assert escape("'target' was unexpected") in r.text


@pytest.mark.asyncio
async def test_valid_info_source_detail_has_no_notice(client, session):
    src = InfoSource(
        url="https://example.com/registry-valid",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )
    session.add(src)
    await session.flush()

    r = await client.get(f"/dashboard/info-sources/{src.info_source_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert 'id="stored-document-notice"' not in r.text


@pytest.mark.asyncio
async def test_info_item_detail_notice(client, session):
    item = InfoItem(name="notice-item", watch_spec={"schema_version": 1, "active": False})
    session.add(item)
    await session.flush()

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert 'id="stored-document-notice"' in r.text
    assert "Watch spec" in r.text


@pytest.mark.asyncio
async def test_rep_spec_detail_notice(client, session):
    spec = RepSpec(
        provider="gcs", name="notice-spec", schema_version=1, document=_gcs_doc(folder_id="x")
    )
    session.add(spec)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)

    assert r.status_code == 200
    assert 'id="stored-document-notice"' in r.text
    assert "folder_id" in r.text
