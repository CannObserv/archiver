"""Tests for /dashboard/rep-specs/ routes."""

import json
from datetime import UTC, datetime

import pytest
from ulid import ULID

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
    "path_template": "items/{source_revision.id}.json",
    "required_fields": [],
}


def _make_rep_spec(name: str = "Test Spec", provider: str = "gcs") -> RepSpec:
    doc = {
        "provider": provider,
        "credentials_alias": "default",
        "path_template": "items/{source_revision.id}.json",
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
        "path_template": "{source_revision.id}",
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
    assert 'id="rep-spec-assignments"' in r.text
    assert (
        f'hx-delete="/dashboard/rep-specs/{spec.rep_spec_id}/assignments/{assignment.id}"' in r.text
    )
    assert 'hx-target="#rep-spec-assignments"' in r.text
    assert "Deactivate" in r.text


@pytest.mark.asyncio
async def test_deactivate_assignment_rerenders_section(client, session):
    """Deactivating re-renders the whole Active Assignments section: the row is
    gone, the count decrements, and the empty-state shows once none remain (#80)."""
    spec = _make_rep_spec("Section Spec")
    session.add(spec)
    await session.flush()
    item_a = InfoItem(name="Assign-A")
    item_b = InfoItem(name="Assign-B")
    session.add(item_a)
    session.add(item_b)
    await session.flush()
    a = InfoItemRepSpec(
        info_item_id=item_a.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    b = InfoItemRepSpec(
        info_item_id=item_b.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 2, tzinfo=UTC),
    )
    session.add(a)
    session.add(b)
    await session.flush()

    # Deactivate A → section re-renders with only B and count (1).
    r = await client.delete(
        f"/dashboard/rep-specs/{spec.rep_spec_id}/assignments/{a.id}", headers=_HEADERS
    )
    assert r.status_code == 200
    assert 'id="rep-spec-assignments"' in r.text
    assert "Assign-B" in r.text
    assert "Assign-A" not in r.text
    assert "Active Assignments (1)" in r.text

    # Reload consistency: A stays gone, B remains.
    r2 = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert "Assign-A" not in r2.text
    assert "Assign-B" in r2.text

    # Deactivate B → empty-state.
    r3 = await client.delete(
        f"/dashboard/rep-specs/{spec.rep_spec_id}/assignments/{b.id}", headers=_HEADERS
    )
    assert r3.status_code == 200
    assert "No active assignments." in r3.text


@pytest.mark.asyncio
async def test_deactivate_assignment_moves_focus_on_swap_only(client, session):
    """The swap fragment focuses the section heading; a plain page load does not (#80 CR15)."""
    spec = _make_rep_spec("Focus Spec")
    session.add(spec)
    await session.flush()
    item = InfoItem(name="Focus Item")
    session.add(item)
    await session.flush()
    a = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(a)
    await session.flush()

    page = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert 'id="rep-spec-assignments-heading"' in page.text
    assert 'getElementById("rep-spec-assignments-heading")' not in page.text  # no focus on load

    swap = await client.delete(
        f"/dashboard/rep-specs/{spec.rep_spec_id}/assignments/{a.id}", headers=_HEADERS
    )
    assert 'getElementById("rep-spec-assignments-heading")' in swap.text  # focus after swap


@pytest.mark.asyncio
async def test_deactivate_assignment_is_idempotent(client, session):
    """A repeat deactivate does not overwrite the original deactivated_at (#80 CR14)."""
    spec = _make_rep_spec("Idem Spec")
    session.add(spec)
    await session.flush()
    item = InfoItem(name="Idem Item")
    session.add(item)
    await session.flush()
    a = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(a)
    await session.flush()

    r1 = await client.delete(
        f"/dashboard/rep-specs/{spec.rep_spec_id}/assignments/{a.id}", headers=_HEADERS
    )
    assert r1.status_code == 200
    await session.refresh(a)
    first_ts = a.deactivated_at
    assert first_ts is not None

    r2 = await client.delete(
        f"/dashboard/rep-specs/{spec.rep_spec_id}/assignments/{a.id}", headers=_HEADERS
    )
    assert r2.status_code == 200
    await session.refresh(a)
    assert a.deactivated_at == first_ts  # unchanged


@pytest.mark.asyncio
async def test_deactivate_assignment_wrong_spec_404(client, session):
    """An assignment under a different spec cannot be deactivated via this spec (#80)."""
    spec_a = _make_rep_spec("Spec A")
    spec_b = _make_rep_spec("Spec B")
    session.add(spec_a)
    session.add(spec_b)
    await session.flush()
    item = InfoItem(name="Cross Item")
    session.add(item)
    await session.flush()
    assignment_b = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec_b.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(assignment_b)
    await session.flush()

    r = await client.delete(
        f"/dashboard/rep-specs/{spec_a.rep_spec_id}/assignments/{assignment_b.id}",
        headers=_HEADERS,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_assignment_unauthenticated_redirects(client, session):
    spec = _make_rep_spec("Auth Spec")
    session.add(spec)
    await session.flush()
    item = InfoItem(name="Auth Item")
    session.add(item)
    await session.flush()
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(assignment)
    await session.flush()

    r = await client.delete(
        f"/dashboard/rep-specs/{spec.rep_spec_id}/assignments/{assignment.id}",
        follow_redirects=False,
    )
    assert r.status_code == 307


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


# ---------------------------------------------------------------------------
# Document editing (archiver#83, tiers 1+2)
#
# The card is editable only while the RepSpec is a draft (zero assignment rows,
# active or deactivated). Assigned specs render read-only with the assignment
# count and a pointer to the clone+migrate flow (#95).
# ---------------------------------------------------------------------------

_DOC_URL = "/dashboard/rep-specs/{}/document"


async def _assigned_spec(session, *, name: str = "Assigned", deactivated: bool = False) -> RepSpec:
    spec = _make_rep_spec(name)
    session.add(spec)
    await session.flush()
    item = InfoItem(name=f"item-{name}")
    session.add(item)
    await session.flush()
    session.add(
        InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
            activated_at=datetime(2026, 4, 1, tzinfo=UTC),
            deactivated_at=datetime(2026, 5, 1, tzinfo=UTC) if deactivated else None,
        )
    )
    await session.flush()
    return spec


@pytest.mark.asyncio
async def test_draft_detail_shows_document_editor(client, session):
    spec = _make_rep_spec("Draft Spec")
    session.add(spec)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'id="rep-spec-document-card"' in r.text
    assert f'hx-post="{_DOC_URL.format(spec.rep_spec_id)}"' in r.text
    assert 'name="document"' in r.text


@pytest.mark.asyncio
async def test_assigned_detail_hides_document_editor(client, session):
    spec = await _assigned_spec(session, name="Frozen Spec")

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'name="document"' not in r.text
    assert "frozen" in r.text.lower()


@pytest.mark.asyncio
async def test_deactivated_assignment_still_freezes_editor(client, session):
    """A deactivated assignment still means a run happened under this document."""
    spec = await _assigned_spec(session, name="Once Assigned", deactivated=True)

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert 'name="document"' not in r.text


@pytest.mark.asyncio
async def test_update_document_on_draft_persists(client, session):
    spec = _make_rep_spec("Editable")
    session.add(spec)
    await session.flush()
    await session.commit()

    new_doc = dict(_GCS_DOC, path_template="corrected/{source_revision.id}.json")
    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        headers=_HEADERS,
        data={"document": json.dumps(new_doc)},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    await session.refresh(spec)
    assert spec.document["path_template"] == "corrected/{source_revision.id}.json"
    assert spec.updated_at is not None


@pytest.mark.asyncio
async def test_update_document_htmx_swaps_card_with_toast(client, session):
    spec = _make_rep_spec("Htmx Editable")
    session.add(spec)
    await session.flush()
    await session.commit()

    new_doc = dict(_GCS_DOC, path_template="swapped/{source_revision.id}.json")
    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        headers={**_HEADERS, "HX-Request": "true"},
        data={"document": json.dumps(new_doc)},
    )
    assert r.status_code == 200
    assert 'id="rep-spec-document-card"' in r.text
    assert "showFlash" in r.headers.get("HX-Trigger", "")
    assert "swapped/" in r.text


@pytest.mark.asyncio
async def test_update_document_invalid_json_rerenders_with_error(client, session):
    spec = _make_rep_spec("Bad JSON")
    session.add(spec)
    await session.flush()
    await session.commit()
    original = dict(spec.document)

    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        headers={**_HEADERS, "HX-Request": "true"},
        data={"document": "{not json"},
    )
    assert r.status_code == 200
    assert 'role="alert"' in r.text
    assert "{not json" in r.text  # operator's text preserved

    await session.refresh(spec)
    assert spec.document == original


@pytest.mark.asyncio
async def test_update_document_schema_error_rerenders_with_error(client, session):
    spec = _make_rep_spec("Bad Schema")
    session.add(spec)
    await session.flush()
    await session.commit()

    bad = dict(_GCS_DOC)
    del bad["path_template"]
    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        headers={**_HEADERS, "HX-Request": "true"},
        data={"document": json.dumps(bad)},
    )
    assert r.status_code == 200
    assert 'role="alert"' in r.text
    assert "path_template" in r.text


@pytest.mark.asyncio
async def test_update_document_provider_change_rejected(client, session):
    spec = _make_rep_spec("Provider Freeze")
    session.add(spec)
    await session.flush()
    await session.commit()

    swapped = dict(_GCS_DOC, provider="gdrive")
    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        headers={**_HEADERS, "HX-Request": "true"},
        data={"document": json.dumps(swapped)},
    )
    assert r.status_code == 200
    assert 'role="alert"' in r.text
    assert "immutable" in r.text.lower()


@pytest.mark.asyncio
async def test_update_document_on_assigned_spec_rejected(client, session):
    spec = await _assigned_spec(session, name="Frozen Post")
    await session.commit()
    original = dict(spec.document)

    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        headers={**_HEADERS, "HX-Request": "true"},
        data={"document": json.dumps(dict(_GCS_DOC, path_template="nope/{info_item_id}"))},
    )
    assert r.status_code == 200
    assert 'role="alert"' in r.text

    await session.refresh(spec)
    assert spec.document == original


@pytest.mark.asyncio
async def test_update_document_unauthenticated_redirects(client, session):
    spec = _make_rep_spec("Unauth Doc")
    session.add(spec)
    await session.flush()
    await session.commit()

    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        data={"document": json.dumps(_GCS_DOC)},
        follow_redirects=False,
    )
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_update_document_not_found_returns_404(client):
    r = await client.post(
        _DOC_URL.format("01J0000000000000000000000Z"),
        headers=_HEADERS,
        data={"document": json.dumps(_GCS_DOC)},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_detail_shows_updated_at_once_edited(client, session):
    spec = _make_rep_spec("Edited Spec")
    spec.updated_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    session.add(spec)
    await session.flush()

    r = await client.get(f"/dashboard/rep-specs/{spec.rep_spec_id}", headers=_HEADERS)
    assert r.status_code == 200
    assert "2026-06-01" in r.text


@pytest.mark.asyncio
async def test_non_htmx_document_error_rerenders_full_page_without_focus_scripts(client, session):
    """The no-JS 422 fallback must not emit the HTMX focus scripts (CR round 1).

    `swapped` is shared by _document_card.html and _assignments.html; leaking it
    into the full-page render made both fire, and the assignments one stole focus
    away from the announced error.
    """
    spec = _make_rep_spec("No JS Error")
    session.add(spec)
    await session.flush()
    await session.commit()

    bad = dict(_GCS_DOC)
    del bad["path_template"]
    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        headers=_HEADERS,  # no HX-Request
        data={"document": json.dumps(bad)},
    )
    assert r.status_code == 422
    assert 'role="alert"' in r.text  # error is still announced
    assert "getElementById" not in r.text  # neither focus script rendered
    assert json.dumps(bad) in r.text or "credentials_alias" in r.text  # input preserved


@pytest.mark.asyncio
async def test_htmx_document_error_still_moves_focus(client, session):
    """Guard the other side: the HTMX partial must keep its focus script."""
    spec = _make_rep_spec("Htmx Focus")
    session.add(spec)
    await session.flush()
    await session.commit()

    bad = dict(_GCS_DOC)
    del bad["path_template"]
    r = await client.post(
        _DOC_URL.format(spec.rep_spec_id),
        headers={**_HEADERS, "HX-Request": "true"},
        data={"document": json.dumps(bad)},
    )
    assert r.status_code == 200
    assert "rep-spec-document-heading" in r.text
    assert "getElementById" in r.text
