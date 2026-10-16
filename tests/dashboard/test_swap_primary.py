"""Tests for swap-primary-source and swap-primary-by-id dashboard endpoints.

Covers:
  POST /dashboard/info-items/{id}/swap-primary-source  — author new source inline
  POST /dashboard/info-items/{id}/swap-primary-by-id   — bind existing source by ULID

Both run the ``swap_primary_source`` core tool (archiver#45), the one the API's
``PUT /info-items/{id}/primary-source`` runs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource

_HEADERS = {"X-ExeDev-UserID": "ext-swap", "X-ExeDev-Email": "swap@example.com"}
_TS = "2026-06-11T12:00:00+00:00"
_SPEC = '[{"schema_version":1,"extraction":{"algorithm":"full_page"},"fingerprint":{}}]'


# ---------------------------------------------------------------------------
# POST /swap-primary-source — new source created + bound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_swap_primary_source_creates_binding(client, session):
    """New InfoSource created and bound as active primary."""
    item = InfoItem(name="swap-creates")
    src_old = InfoSource(url="https://old.swap-creates.example.com/", source_specs=[])
    session.add(item)
    session.add(src_old)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src_old.info_source_id,
        )
    )
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://new.swap-creates.example.com/", "source_specs": _SPEC},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]

    await session.refresh(item)
    bindings = list(
        (
            await session.execute(
                select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
            )
        )
        .scalars()
        .all()
    )
    active = [b for b in bindings if b.deactivated_at is None]
    assert len(active) == 1
    assert active[0].info_source_id != src_old.info_source_id


@pytest.mark.asyncio
async def test_swap_primary_source_deactivates_old(client, session):
    """Old active binding gains deactivated_at after swap."""
    item = InfoItem(name="swap-deactivates-old")
    src_old = InfoSource(url="https://old.deactivate-old.example.com/", source_specs=[])
    session.add(item)
    session.add(src_old)
    await session.flush()
    old_source_id = src_old.info_source_id
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=old_source_id,
        )
    )
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://new.deactivate-old.example.com/", "source_specs": _SPEC},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]

    old_binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.info_source_id == old_source_id,
            )
        )
    ).scalar_one_or_none()
    assert old_binding is not None
    assert old_binding.deactivated_at is not None


@pytest.mark.asyncio
async def test_swap_primary_source_invalid_url(client, session):
    """Invalid URL returns 422."""
    item = InfoItem(name="swap-bad-url")
    session.add(item)
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "not-a-url", "source_specs": "[]"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
    assert "swap-error" in r.text
    assert "text-danger" in r.text


@pytest.mark.asyncio
async def test_swap_primary_source_invalid_specs(client, session):
    """Non-JSON source_specs returns 422."""
    item = InfoItem(name="swap-bad-specs")
    session.add(item)
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://example.com/page", "source_specs": "not-json"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
    assert "swap-error" in r.text
    assert "text-danger" in r.text


# ---------------------------------------------------------------------------
# POST /swap-primary-by-id — bind existing InfoSource
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_swap_primary_by_id_binds_existing(client, session):
    """Old binding deactivated; new source becomes active primary."""
    item = InfoItem(name="swap-by-id-binds")
    src_old = InfoSource(url="https://old.byid.example.com/", source_specs=[])
    src_new = InfoSource(url="https://new.byid.example.com/", source_specs=[])
    session.add_all([item, src_old, src_new])
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src_old.info_source_id,
        )
    )
    await session.commit()
    new_id = src_new.info_source_id

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-by-id",
        data={"info_source_id": str(new_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]

    bindings = list(
        (
            await session.execute(
                select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
            )
        )
        .scalars()
        .all()
    )
    active = [b for b in bindings if b.deactivated_at is None]
    assert len(active) == 1
    assert active[0].info_source_id == new_id


@pytest.mark.asyncio
async def test_swap_primary_by_id_invalid_ulid(client, session):
    """Non-ULID info_source_id returns 422."""
    item = InfoItem(name="swap-by-id-bad-ulid")
    session.add(item)
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-by-id",
        data={"info_source_id": "not-a-ulid"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
    assert "swap-by-id-error" in r.text
    assert "text-danger" in r.text


# ---------------------------------------------------------------------------
# Shared core tool (archiver#45)
# ---------------------------------------------------------------------------


async def _primary_changed(session) -> list[dict]:
    payloads = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.changes")
        )
    ).scalars()
    return [p for p in payloads if p["event_type"] == "info_item_primary_changed"]


async def _bound_item(session, name: str) -> tuple[InfoItem, InfoSource]:
    item = InfoItem(name=name)
    src = InfoSource(url=f"https://old.{name}.example.com/", source_specs=[])
    session.add_all([item, src])
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.commit()
    return item, src


@pytest.mark.asyncio
async def test_swap_primary_source_emits_primary_changed(client, session):
    """The dashboard swap is a succession on ``info.changes`` like the API's."""
    item, old = await _bound_item(session, "swap-emits")

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://new.swap-emits.example.com/", "source_specs": _SPEC},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204

    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["old_info_source_id"] == str(old.info_source_id)


@pytest.mark.asyncio
async def test_swap_primary_by_id_emits_primary_changed(client, session):
    item, old = await _bound_item(session, "swap-by-id-emits")
    new = InfoSource(url="https://new.swap-by-id-emits.example.com/", source_specs=[])
    session.add(new)
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-by-id",
        data={"info_source_id": str(new.info_source_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204

    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["old_info_source_id"] == str(old.info_source_id)
    assert events[0]["new_info_source_id"] == str(new.info_source_id)


@pytest.mark.asyncio
async def test_swap_primary_by_id_to_the_current_primary_writes_nothing(client, session):
    """It used to deactivate and re-insert the same (item, source) key: a 500."""
    item, src = await _bound_item(session, "swap-by-id-same")

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-by-id",
        data={"info_source_id": str(src.info_source_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204

    binding = await session.get(InfoItemSource, (item.info_item_id, src.info_source_id))
    await session.refresh(binding)
    assert binding.deactivated_at is None
    assert await _primary_changed(session) == []


@pytest.mark.asyncio
async def test_swap_primary_by_id_to_a_previous_primary_reactivates_it(client, session):
    """It used to insert a second (item, source) key: a 500."""
    item, current = await _bound_item(session, "swap-by-id-earlier")
    earlier = InfoSource(url="https://earlier.swap-by-id.example.com/", source_specs=[])
    session.add(earlier)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=earlier.info_source_id,
            deactivated_at=datetime.now(UTC),
        )
    )
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-by-id",
        data={"info_source_id": str(earlier.info_source_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204

    reactivated = await session.get(InfoItemSource, (item.info_item_id, earlier.info_source_id))
    retired = await session.get(InfoItemSource, (item.info_item_id, current.info_source_id))
    await session.refresh(reactivated)
    await session.refresh(retired)
    assert reactivated.deactivated_at is None
    assert retired.deactivated_at is not None
