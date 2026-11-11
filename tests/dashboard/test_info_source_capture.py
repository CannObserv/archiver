"""Capture now on InfoSource detail (archiver#380 slice A).

Covers:
  POST /dashboard/info-sources/{id}/capture-now
  GET  /dashboard/info-sources/{id}/capture      (the card's poll)
  the #capture-card on GET /dashboard/info-sources/{id}

1. Switch off: no card, both routes 404, nothing enqueued
2. Switch on: the card and its button; a POST swaps the card in place, writes
   one command + one outbox row, requested_by the operator
3. One open command per source: requested disables the button and polls; a
   POST while open writes nothing and flashes
4. Each state renders: stored (metadata, not the image), failed (reason
   verbatim, status code), abandoned (names the horizon and the DLQ)
5. No-JS fallback: a plain POST is a 303 to detail
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from co_core.pure.adapters.bus.streams import CONTENT_CAPTURE
from sqlalchemy import func, select
from ulid import ULID

from src.core.models import AppUser, CaptureCommand, ChangesOutboxRow, InfoSource
from src.core.services.capture import ENABLED_ENV
from tests.dashboard.conftest import poll_sync_violations, read_flash

_HEADERS = {"X-ExeDev-UserID": "ext-capture", "X-ExeDev-Email": "capture@example.com"}
_HTMX = {**_HEADERS, "HX-Request": "true"}
DIGEST = "d" * 64


@pytest.fixture
def capture_on(monkeypatch):
    monkeypatch.setenv(ENABLED_ENV, "1")


@pytest.fixture
def capture_off(monkeypatch):
    monkeypatch.delenv(ENABLED_ENV, raising=False)


async def _source(session) -> InfoSource:
    source = InfoSource(url="https://example.com/capture-page", source_specs=[])
    session.add(source)
    await session.flush()
    return source


def _command(source: InfoSource, *, state: str = "requested", ago=timedelta(seconds=5), **fields):
    values = dict(
        command_id=str(ULID()),
        info_source_id=source.info_source_id,
        url=source.url,
        viewport_width=1280,
        viewport_height=800,
        full_page=True,
        issued_at=datetime.now(UTC) - ago,
        state=state,
    )
    values.update(fields)
    return CaptureCommand(**values)


async def _detail(client, source):
    return await client.get(f"/dashboard/info-sources/{source.info_source_id}", headers=_HEADERS)


async def _card(client, source):
    return await client.get(
        f"/dashboard/info-sources/{source.info_source_id}/capture", headers=_HTMX
    )


async def _capture_now(client, source, headers=_HTMX):
    return await client.post(
        f"/dashboard/info-sources/{source.info_source_id}/capture-now",
        headers=headers,
        follow_redirects=False,
    )


async def _count(session, column) -> int:
    return (await session.execute(select(func.count(column)))).scalar_one()


def _card_html(text: str) -> str:
    return text[text.index('id="capture-card"') :]


# ---------------------------------------------------------------------------
# 1. Switch off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_off_offers_no_card(client, session, capture_off):
    source = await _source(session)
    r = await _detail(client, source)
    assert r.status_code == 200
    assert 'id="capture-card"' not in r.text
    assert "capture-now" not in r.text


@pytest.mark.asyncio
async def test_switch_off_routes_are_404_and_enqueue_nothing(client, session, capture_off):
    source = await _source(session)
    assert (await _card(client, source)).status_code == 404
    assert (await _capture_now(client, source)).status_code == 404
    assert await _count(session, CaptureCommand.command_id) == 0
    assert await _count(session, ChangesOutboxRow.id) == 0


# ---------------------------------------------------------------------------
# 2. Switch on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_card_offers_the_button(client, session, capture_on):
    source = await _source(session)

    r = await _detail(client, source)

    card = _card_html(r.text)
    assert "Viewport Capture" in card
    assert "Not captured yet" in card
    assert f'hx-post="/dashboard/info-sources/{source.info_source_id}/capture-now"' in card
    assert 'hx-target="#capture-card"' in card
    assert "Capture now" in card
    # The profile slice A sends, stated so the operator knows what they asked for.
    assert "1280×800" in card
    assert "every " not in card
    assert "disabled" not in card


@pytest.mark.asyncio
async def test_post_enqueues_one_command_for_the_operator(client, session, capture_on):
    source = await _source(session)

    r = await _capture_now(client, source)

    assert r.status_code == 200
    [command] = (await session.execute(select(CaptureCommand))).scalars().all()
    [outbox] = (await session.execute(select(ChangesOutboxRow))).scalars().all()
    assert outbox.topic == CONTENT_CAPTURE
    assert outbox.payload["command_id"] == command.command_id
    user = (
        await session.execute(select(AppUser).where(AppUser.external_id == "ext-capture"))
    ).scalar_one()
    assert command.requested_by == user.id
    # The swapped card shows the open command and polls.
    assert "Capture pending" in r.text
    assert "every " in r.text
    assert poll_sync_violations(r.text, "capture-card") == []


@pytest.mark.asyncio
async def test_plain_post_redirects_to_detail(client, session, capture_on):
    source = await _source(session)
    r = await _capture_now(client, source, headers=_HEADERS)
    assert r.status_code == 303
    assert r.headers["location"] == f"/dashboard/info-sources/{source.info_source_id}"
    assert await _count(session, CaptureCommand.command_id) == 1


@pytest.mark.asyncio
async def test_post_for_an_unknown_source_is_404(client, capture_on):
    r = await client.post(f"/dashboard/info-sources/{ULID()}/capture-now", headers=_HTMX)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. One open command per source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_requested_disables_the_button_and_polls(client, session, capture_on):
    source = await _source(session)
    session.add(_command(source))
    await session.flush()

    for r in (await _detail(client, source), await _card(client, source)):
        assert r.status_code == 200
        card = _card_html(r.text)
        assert "Capture pending" in card
        assert f'hx-get="/dashboard/info-sources/{source.info_source_id}/capture"' in card
        assert "every " in card
        assert "disabled" in card
        assert poll_sync_violations(r.text, "capture-card") == []


@pytest.mark.asyncio
async def test_post_while_open_writes_nothing_and_flashes(client, session, capture_on):
    source = await _source(session)
    session.add(_command(source))
    await session.flush()

    r = await _capture_now(client, source)

    assert r.status_code == 200
    assert await _count(session, CaptureCommand.command_id) == 1
    assert await _count(session, ChangesOutboxRow.id) == 0
    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "warning"
    assert "already pending" in flash["body"]


# ---------------------------------------------------------------------------
# 4. Each state, rendered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stored_shows_the_metadata_not_the_image(client, session, capture_on):
    source = await _source(session)
    captured = datetime.now(UTC) - timedelta(minutes=3)
    session.add(
        _command(
            source,
            state="stored",
            ago=timedelta(minutes=4),
            content_fingerprint=DIGEST,
            blob_uri=f"gs://co-gcs-blobs/blobs/{DIGEST}.bin",
            media_type="image/png",
            size_bytes=2_500_000,
            image_width=1280,
            image_height=9001,
            final_url="https://example.com/capture-page?landed=1",
            captured_at=captured,
            blob_expires_at=datetime(2030, 1, 2, 3, 4, tzinfo=UTC),
            closed_at=datetime.now(UTC),
        )
    )
    await session.flush()

    card = _card_html((await _card(client, source)).text)

    assert "Stored" in card
    assert "1280 × 9001" in card
    assert "2.5 MB" in card
    assert DIGEST in card
    assert "https://example.com/capture-page?landed=1" in card
    assert f"gs://co-gcs-blobs/blobs/{DIGEST}.bin" in card
    assert "2030-01-02 03:04 UTC" in card
    assert "<img" not in card
    assert "every " not in card
    assert "disabled" not in card


@pytest.mark.asyncio
async def test_stored_past_its_horizon_reads_expired(client, session, capture_on):
    source = await _source(session)
    session.add(
        _command(
            source,
            state="stored",
            content_fingerprint=DIGEST,
            blob_uri="gs://x",
            media_type="image/png",
            size_bytes=1,
            image_width=1,
            image_height=1,
            final_url=source.url,
            captured_at=datetime.now(UTC) - timedelta(days=8),
            blob_expires_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await session.flush()

    card = _card_html((await _card(client, source)).text)
    assert "expired" in card


@pytest.mark.asyncio
async def test_failed_shows_the_reason_verbatim(client, session, capture_on):
    source = await _source(session)
    session.add(
        _command(
            source,
            state="failed",
            reason="http_status",
            status_code=403,
            detail="navigation answered 403",
            terminal=True,
        )
    )
    await session.flush()

    card = _card_html((await _card(client, source)).text)

    assert "Capture failed" in card
    assert "<code>http_status</code>" in card
    assert "403" in card
    assert "navigation answered 403" in card
    assert "disabled" not in card


@pytest.mark.asyncio
async def test_abandoned_names_the_horizon_and_the_dlq(client, session, capture_on):
    source = await _source(session)
    session.add(
        _command(source, state="abandoned", reason="no_fact_before_horizon", ago=timedelta(hours=2))
    )
    await session.flush()

    card = _card_html((await _card(client, source)).text)

    assert "No answer" in card
    assert "60 min" in card
    assert "content.capture.dlq" in card
    assert "disabled" not in card


@pytest.mark.asyncio
async def test_only_the_latest_command_is_shown(client, session, capture_on):
    source = await _source(session)
    session.add(_command(source, state="failed", reason="old_reason", ago=timedelta(hours=3)))
    session.add(_command(source, state="failed", reason="new_reason", ago=timedelta(minutes=1)))
    await session.flush()

    card = _card_html((await _card(client, source)).text)
    assert "new_reason" in card
    assert "old_reason" not in card


@pytest.mark.asyncio
async def test_a_kept_capture_reads_kept_not_an_expiry(client, session, capture_on):
    """Slice B: once persisted, blob_expires_at no longer binds."""
    source = await _source(session)
    session.add(
        _command(
            source,
            state="stored",
            content_fingerprint=DIGEST,
            blob_uri="gs://x",
            media_type="image/png",
            size_bytes=1,
            image_width=1,
            image_height=1,
            final_url=source.url,
            captured_at=datetime.now(UTC) - timedelta(days=8),
            blob_expires_at=datetime.now(UTC) - timedelta(days=1),
            persisted_at=datetime(2030, 1, 2, 3, 5, tzinfo=UTC),
        )
    )
    await session.flush()

    card = _card_html((await _card(client, source)).text)

    assert "Kept" in card
    assert "2030-01-02 03:05 UTC" in card
    assert "expired" not in card
