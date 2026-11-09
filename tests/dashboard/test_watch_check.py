"""Check-now on the Watcher panel (archiver#370, epic #359 A11).

Covers:
  POST /dashboard/info-items/{id}/check-now
  GET  /dashboard/info-items/{id}/watch-check   (the block's poll)
  the #watch-check block inside GET /watcher-section

1. Switch off (D6): no button, both routes 404, nothing enqueued
2. Switch on: the button, the shared Watcher-POST contract, one command +
   one outbox row, requested_by the operator
3. One open command per item (D4): pending disables the button; a POST while
   pending writes nothing and flashes
4. Each rung of the ladder renders (D2): pending (polls), done (+ health and
   reason), rejected (verbatim), no answer yet (names the DLQ)
5. Not offered on an item outside the announced set
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from ulid import ULID

from src.core.models import AppUser, ChangesOutboxRow, InfoItem, WatchCheckCommand, WatchStatus
from src.core.services.watch_check import DEFAULT_TIMEOUT, ENABLED_ENV
from tests.dashboard.conftest import poll_sync_violations, read_flash

_HEADERS = {"X-ExeDev-UserID": "ext-check-now", "X-ExeDev-Email": "check@example.com"}


@pytest.fixture
def check_on(monkeypatch):
    monkeypatch.setenv(ENABLED_ENV, "1")


@pytest.fixture
def check_off(monkeypatch):
    monkeypatch.delenv(ENABLED_ENV, raising=False)


async def _watched(session, bind_source, *, last_full_fetch_at=None, **status) -> InfoItem:
    item = InfoItem(name="check-now item")
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug=f"check-{item.info_item_id}")
    values = dict(
        info_item_id=item.info_item_id,
        applied_generation=item.announcement_generation,
        applied_active=True,
        health="ok",
        last_full_fetch_at=last_full_fetch_at,
        occurred_at=datetime.now(UTC),
    )
    values.update(status)
    session.add(WatchStatus(**values))
    await session.flush()
    return item


def _command(item: InfoItem, *, ago: timedelta = timedelta(seconds=5), **fields):
    return WatchCheckCommand(
        command_id=str(ULID()),
        info_item_id=item.info_item_id,
        requested_at=datetime.now(UTC) - ago,
        **fields,
    )


async def _section(client, item):
    return await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section", headers=_HEADERS
    )


async def _block(client, item):
    return await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watch-check", headers=_HEADERS
    )


async def _check_now(client, item):
    return await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now", headers=_HEADERS
    )


async def _count(session, column) -> int:
    return (await session.execute(select(func.count(column)))).scalar_one()


# ---------------------------------------------------------------------------
# Switch off: dark (D6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_off_offers_no_button(client, session, bind_source, check_off):
    item = await _watched(session, bind_source)

    r = await _section(client, item)

    assert r.status_code == 200
    assert "check-now" not in r.text
    assert 'id="watch-check"' not in r.text


@pytest.mark.asyncio
async def test_switch_off_post_is_404_and_enqueues_nothing(client, session, bind_source, check_off):
    item = await _watched(session, bind_source)

    r = await _check_now(client, item)

    assert r.status_code == 404
    assert await _count(session, WatchCheckCommand.command_id) == 0
    assert await _count(session, ChangesOutboxRow.id) == 0


@pytest.mark.asyncio
async def test_switch_off_poll_is_404(client, session, bind_source, check_off):
    item = await _watched(session, bind_source)
    assert (await _block(client, item)).status_code == 404


# ---------------------------------------------------------------------------
# Switch on: the button and the POST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_button_follows_the_watcher_post_contract(client, session, bind_source, check_on):
    item = await _watched(session, bind_source)

    r = await _section(client, item)

    assert 'id="watch-check"' in r.text
    assert f'hx-post="/dashboard/info-items/{item.info_item_id}/check-now"' in r.text
    block = r.text[r.text.index('id="watch-check"') :]
    assert 'hx-swap="none"' in block
    assert "watcher-heading" in block
    assert "Check now" in block
    # Never checked: no poll.
    assert "every " not in block
    # #watcher-section is the live region; the block swaps itself whole, and a
    # region inserted fresh is not reliably announced (#370 CR 4).
    assert "aria-live" not in block


@pytest.mark.asyncio
async def test_post_enqueues_one_command_for_the_operator(client, session, bind_source, check_on):
    item = await _watched(session, bind_source)

    r = await _check_now(client, item)

    assert r.status_code == 200
    assert "watcherUpdated" in json.loads(r.headers["HX-Trigger"])
    [command] = (await session.execute(select(WatchCheckCommand))).scalars().all()
    [outbox] = (await session.execute(select(ChangesOutboxRow))).scalars().all()
    assert outbox.topic == "info.watch-check"
    assert outbox.payload["command_id"] == command.command_id
    user = (
        await session.execute(select(AppUser).where(AppUser.external_id == "ext-check-now"))
    ).scalar_one()
    assert command.requested_by == user.id


@pytest.mark.asyncio
async def test_post_while_pending_writes_nothing_and_flashes(
    client, session, bind_source, check_on
):
    item = await _watched(session, bind_source)
    session.add(_command(item))
    await session.flush()

    r = await _check_now(client, item)

    assert r.status_code == 200
    assert await _count(session, WatchCheckCommand.command_id) == 1
    assert await _count(session, ChangesOutboxRow.id) == 0
    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "warning"
    assert "already pending" in flash["body"]


@pytest.mark.asyncio
async def test_post_for_an_unknown_item_is_404(client, check_on):
    r = await client.post(f"/dashboard/info-items/{ULID()}/check-now", headers=_HEADERS)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# The ladder, rendered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_disables_the_button_and_polls(client, session, bind_source, check_on):
    item = await _watched(session, bind_source)
    session.add(_command(item))
    await session.flush()

    for r in (await _section(client, item), await _block(client, item)):
        assert r.status_code == 200
        assert "Check pending" in r.text
        block = r.text[r.text.index('id="watch-check"') :]
        assert f'hx-get="/dashboard/info-items/{item.info_item_id}/watch-check"' in block
        assert "every " in block
        assert "disabled" in block
        assert poll_sync_violations(r.text, "watch-check") == []


@pytest.mark.asyncio
async def test_done_shows_the_health(client, session, bind_source, check_on):
    item = await _watched(session, bind_source, last_full_fetch_at=datetime.now(UTC))
    session.add(_command(item, ago=timedelta(minutes=1)))
    await session.flush()

    r = await _block(client, item)

    assert "Checked" in r.text
    assert "OK" in r.text
    assert "every " not in r.text
    assert "disabled" not in r.text


@pytest.mark.asyncio
async def test_done_with_an_error_shows_the_reason_and_code(client, session, bind_source, check_on):
    item = await _watched(
        session,
        bind_source,
        last_full_fetch_at=datetime.now(UTC),
        health="error",
        health_reason="http_status",
        health_status_code=503,
    )
    session.add(_command(item, ago=timedelta(minutes=1)))
    await session.flush()

    r = await _block(client, item)

    assert "Checked" in r.text
    assert "ERROR" in r.text
    assert "http_status · 503" in r.text


@pytest.mark.asyncio
async def test_done_with_an_error_and_no_reason_says_not_reported(
    client, session, bind_source, check_on
):
    """archiver#371 D3: the panel's rule, through the same macro."""
    item = await _watched(
        session, bind_source, last_full_fetch_at=datetime.now(UTC), health="error"
    )
    session.add(_command(item, ago=timedelta(minutes=1)))
    await session.flush()

    r = await _block(client, item)

    assert "ERROR" in r.text
    assert "reason not reported" in r.text


@pytest.mark.asyncio
async def test_done_ok_hides_a_stored_reason(client, session, bind_source, check_on):
    """archiver#371 D3: reason and code show only when health != ok."""
    item = await _watched(
        session,
        bind_source,
        last_full_fetch_at=datetime.now(UTC),
        health_reason="http_status",
        health_status_code=200,
    )
    session.add(_command(item, ago=timedelta(minutes=1)))
    await session.flush()

    r = await _block(client, item)

    assert "OK" in r.text
    assert "http_status" not in r.text
    assert "not reported" not in r.text


@pytest.mark.asyncio
async def test_rejected_shows_the_reason_verbatim(client, session, bind_source, check_on):
    item = await _watched(session, bind_source)
    session.add(_command(item, rejected_reason="some_future_token", rejected_at=datetime.now(UTC)))
    await session.flush()

    r = await _block(client, item)

    assert "Check rejected" in r.text
    assert "some_future_token" in r.text
    assert "every " not in r.text
    assert "disabled" not in r.text


@pytest.mark.asyncio
async def test_no_answer_names_the_dlq_and_allows_a_new_click(
    client, session, bind_source, check_on
):
    item = await _watched(session, bind_source)
    session.add(_command(item, ago=DEFAULT_TIMEOUT + timedelta(minutes=1)))
    await session.flush()

    r = await _block(client, item)

    assert "No answer yet" in r.text
    assert "info.watch-check.dlq" in r.text
    assert "every " not in r.text
    assert "disabled" not in r.text


@pytest.mark.asyncio
async def test_not_offered_outside_the_announced_set(client, session, check_on):
    item = InfoItem(name="unbound")
    session.add(item)
    await session.flush()

    r = await _section(client, item)

    assert "Not watching" in r.text
    assert 'id="watch-check"' not in r.text
