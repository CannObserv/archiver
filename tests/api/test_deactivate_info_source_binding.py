"""HTTP-layer tests for DELETE /info-items/{id}/info-sources/{source_id}."""

import pytest

from src.core.models import InfoItem, InfoItemSource, InfoSource


def _spec_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


HEADERS = {"X-API-Key": "test-secret-key"}


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


@pytest.fixture
async def root_src(session):
    src = InfoSource(url="https://example.com/p", source_specs=[_spec_doc()])
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def active_binding(session, item, root_src):
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=root_src.info_source_id,
    )
    session.add(binding)
    await session.commit()
    return binding


@pytest.mark.asyncio
async def test_deactivate_binding_200(client, active_binding, item, root_src):
    resp = await client.delete(
        f"/api/v1/info-items/{item.info_item_id}/info-sources/{root_src.info_source_id}",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["info_source_id"] == str(root_src.info_source_id)
    assert body["is_active"] is False
    assert body["deactivated_at"] is not None


@pytest.mark.asyncio
async def test_deactivate_binding_not_found_404(client, item, root_src):
    resp = await client.delete(
        f"/api/v1/info-items/{item.info_item_id}/info-sources/{root_src.info_source_id}",
        headers=HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["kind"] == "lookup"


@pytest.mark.asyncio
async def test_deactivate_already_deactivated_404(client, session, active_binding, item, root_src):
    """Deactivating an already-deactivated binding returns 404."""
    await client.delete(
        f"/api/v1/info-items/{item.info_item_id}/info-sources/{root_src.info_source_id}",
        headers=HEADERS,
    )
    resp = await client.delete(
        f"/api/v1/info-items/{item.info_item_id}/info-sources/{root_src.info_source_id}",
        headers=HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_then_rebind_primary_succeeds(client, session, active_binding, item):
    """Succession workflow: DELETE old primary → POST new primary → 201."""
    root_src = active_binding

    new_src = InfoSource(url="https://example.com/q", source_specs=[_spec_doc()])
    session.add(new_src)
    await session.commit()

    # Deactivate old primary.
    resp = await client.delete(
        f"/api/v1/info-items/{item.info_item_id}/info-sources/{root_src.info_source_id}",
        headers=HEADERS,
    )
    assert resp.status_code == 200

    # Bind new primary.
    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(new_src.info_source_id)},
    )
    assert resp.status_code == 201
    assert resp.json()["is_active"] is True


@pytest.mark.asyncio
async def test_deactivate_requires_auth(client, active_binding, item, root_src):
    """Missing API key → 403 (no key present; 401 is for invalid key)."""
    resp = await client.delete(
        f"/api/v1/info-items/{item.info_item_id}/info-sources/{root_src.info_source_id}",
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_succession_emits_primary_changed_event_with_old_source(
    client, session, active_binding, item
):
    """After succession, info_item_primary_changed carries old_info_source_id."""
    from sqlalchemy import select

    from src.core.models import ChangesOutboxRow

    old_src = active_binding
    new_src = InfoSource(url="https://example.com/new", source_specs=[_spec_doc()])
    session.add(new_src)
    await session.commit()

    # DELETE old primary.
    await client.delete(
        f"/api/v1/info-items/{item.info_item_id}/info-sources/{old_src.info_source_id}",
        headers=HEADERS,
    )
    # POST new primary.
    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(new_src.info_source_id)},
    )
    assert resp.status_code == 201

    rows = (await session.execute(select(ChangesOutboxRow))).scalars().all()
    primary_events = [r for r in rows if r.payload.get("event_type") == "info_item_primary_changed"]
    assert len(primary_events) == 1
    ev = primary_events[0].payload
    assert ev["old_info_source_id"] == str(old_src.info_source_id)
    assert ev["new_info_source_id"] == str(new_src.info_source_id)
