"""HTTP-layer tests for POST /info-items/{id}/info-sources.

Covers happy path, collision guard, existence errors, and bus event emission.
"""

from datetime import UTC, datetime

import pytest

from src.core.models import InfoItem, InfoItemSource, InfoSource

HEADERS = {"X-API-Key": "test-secret-key"}


def _spec() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


async def _make_source(session, url: str = "https://example.com/a") -> InfoSource:
    src = InfoSource(url=url, source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


@pytest.mark.asyncio
async def test_bind_201(client, session, item):
    src = await _make_source(session)
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id)},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_active"] is True
    assert body["deactivated_at"] is None
    assert "role" not in body


@pytest.mark.asyncio
async def test_duplicate_active_binding_returns_409(client, session, item):
    src_a = await _make_source(session, "https://example.com/a")
    src_b = await _make_source(session, "https://example.com/b")
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src_a.info_source_id))
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src_b.info_source_id)},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["kind"] == "conflict"
    assert detail["data"]["existing_info_source_id"] == str(src_a.info_source_id)


@pytest.mark.asyncio
async def test_unknown_info_source_returns_404(client, item):
    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": "01JZZZZZZZZZZZZZZZZZZZZZZZ"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_info_item_returns_404(client, session):
    src = await _make_source(session)
    await session.commit()
    resp = await client.post(
        "/api/v1/info-items/01JZZZZZZZZZZZZZZZZZZZZZZZ/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id)},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_primary_changed_event_emitted_on_first_assignment(client, session, item):
    from sqlalchemy import select

    from src.core.models import ChangesOutboxRow

    src = await _make_source(session)
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id)},
    )
    assert resp.status_code == 201

    rows = (await session.execute(select(ChangesOutboxRow))).scalars().all()
    primary_events = [r for r in rows if r.payload.get("event_type") == "info_item_primary_changed"]
    assert len(primary_events) == 1
    ev = primary_events[0].payload
    assert ev["old_info_source_id"] is None
    assert ev["new_info_source_id"] == str(src.info_source_id)
    assert ev["info_item_id"] == str(item.info_item_id)


@pytest.mark.asyncio
async def test_primary_changed_event_carries_old_source_on_succession(client, session, item):
    from sqlalchemy import select

    from src.core.models import ChangesOutboxRow

    src_a = await _make_source(session, "https://example.com/a")
    src_b = await _make_source(session, "https://example.com/b")
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src_a.info_source_id,
            deactivated_at=datetime.now(UTC),
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src_b.info_source_id)},
    )
    assert resp.status_code == 201

    rows = (await session.execute(select(ChangesOutboxRow))).scalars().all()
    primary_events = [r for r in rows if r.payload.get("event_type") == "info_item_primary_changed"]
    assert len(primary_events) == 1
    ev = primary_events[0].payload
    assert ev["old_info_source_id"] == str(src_a.info_source_id)
    assert ev["new_info_source_id"] == str(src_b.info_source_id)
