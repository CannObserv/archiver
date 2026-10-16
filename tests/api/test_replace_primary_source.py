"""HTTP-layer tests for PUT /info-items/{id}/primary-source (archiver#45).

The atomic swap: one request, one transaction, one ``info.registry``
announcement. DELETE then POST is two flows and announces revoked-then-live.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource

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


async def _source(session, url: str) -> InfoSource:
    src = InfoSource(url=url, source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


async def _outbox(session, topic: str) -> list[dict]:
    result = await session.execute(
        select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == topic)
    )
    return list(result.scalars())


async def _put(client, item_id, source_id):
    return await client.put(
        f"/api/v1/info-items/{item_id}/primary-source",
        headers=HEADERS,
        json={"info_source_id": str(source_id)},
    )


@pytest.mark.asyncio
async def test_first_assignment_is_201(client, session, item):
    src = await _source(session, "https://example.com/a")
    await session.commit()

    resp = await _put(client, item.info_item_id, src.info_source_id)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["info_source_id"] == str(src.info_source_id)
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_replacement_is_200_and_retires_the_old_primary(client, session, item):
    old = await _source(session, "https://example.com/a")
    new = await _source(session, "https://example.com/b")
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=old.info_source_id))
    await session.commit()

    resp = await _put(client, item.info_item_id, new.info_source_id)

    assert resp.status_code == 200, resp.text
    assert resp.json()["info_source_id"] == str(new.info_source_id)
    bindings = {
        b.info_source_id: b
        for b in (
            await session.execute(
                select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
            )
        ).scalars()
    }
    assert bindings[old.info_source_id].deactivated_at is not None
    assert bindings[new.info_source_id].deactivated_at is None


@pytest.mark.asyncio
async def test_replacement_announces_once_and_emits_primary_changed(client, session, item):
    old = await _source(session, "https://example.com/a")
    new = await _source(session, "https://example.com/b")
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=old.info_source_id))
    await session.commit()

    resp = await _put(client, item.info_item_id, new.info_source_id)
    assert resp.status_code == 200, resp.text

    registry = await _outbox(session, "info.registry")
    assert len(registry) == 1
    assert registry[0]["revoked"] is False
    assert registry[0]["info_source_id"] == str(new.info_source_id)
    changed = [
        p
        for p in await _outbox(session, "info.changes")
        if p["event_type"] == "info_item_primary_changed"
    ]
    assert len(changed) == 1
    assert changed[0]["old_info_source_id"] == str(old.info_source_id)
    assert changed[0]["new_info_source_id"] == str(new.info_source_id)


@pytest.mark.asyncio
async def test_putting_the_current_primary_is_a_200_no_op(client, session, item):
    src = await _source(session, "https://example.com/a")
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.commit()

    resp = await _put(client, item.info_item_id, src.info_source_id)

    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True
    assert await _outbox(session, "info.registry") == []
    assert await _outbox(session, "info.changes") == []


@pytest.mark.asyncio
async def test_unknown_item_is_404(client, session):
    src = await _source(session, "https://example.com/a")
    await session.commit()

    resp = await _put(client, "01JZZZZZZZZZZZZZZZZZZZZZZZ", src.info_source_id)

    assert resp.status_code == 404
    assert resp.json()["detail"]["message"] == "InfoItem not found"


@pytest.mark.asyncio
async def test_unknown_source_is_404(client, item):
    resp = await _put(client, item.info_item_id, "01JZZZZZZZZZZZZZZZZZZZZZZZ")

    assert resp.status_code == 404
    assert resp.json()["detail"]["message"] == "InfoSource not found"


@pytest.mark.asyncio
async def test_a_previous_primary_is_reactivated_200(client, session, item):
    """A revert reactivates the history row; the (item, source) key admits no second."""
    earlier = await _source(session, "https://example.com/a")
    current = await _source(session, "https://example.com/b")
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=earlier.info_source_id,
            deactivated_at=datetime.now(UTC),
        )
    )
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=current.info_source_id)
    )
    await session.commit()

    resp = await _put(client, item.info_item_id, earlier.info_source_id)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["info_source_id"] == str(earlier.info_source_id)
    assert body["is_active"] is True
    assert body["deactivated_at"] is None
    registry = await _outbox(session, "info.registry")
    assert len(registry) == 1
    assert registry[0]["info_source_id"] == str(earlier.info_source_id)


@pytest.mark.asyncio
async def test_a_malformed_source_id_is_422(client, item):
    resp = await _put(client, item.info_item_id, "not-a-ulid")

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_api_key(client, item):
    resp = await client.put(
        f"/api/v1/info-items/{item.info_item_id}/primary-source",
        json={"info_source_id": "01JZZZZZZZZZZZZZZZZZZZZZZZ"},
    )

    assert resp.status_code == 403
