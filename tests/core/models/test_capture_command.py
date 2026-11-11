"""CaptureCommand column contracts (archiver#380 slice A)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from src.core.models import AppUser, CaptureCommand, InfoSource

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


async def _source(session) -> InfoSource:
    source = InfoSource(url="https://example.com/capture-me", source_specs=[])
    session.add(source)
    await session.flush()
    return source


def _command(source: InfoSource, state: str = "requested", **overrides) -> CaptureCommand:
    values = dict(
        command_id=str(ULID()),
        info_source_id=source.info_source_id,
        url=source.url,
        viewport_width=1280,
        viewport_height=800,
        full_page=True,
        wait=None,
        issued_at=T0,
        state=state,
    )
    values.update(overrides)
    return CaptureCommand(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["requested", "stored", "failed", "abandoned"])
async def test_known_states_are_accepted(session, state):
    source = await _source(session)
    session.add(_command(source, state))
    await session.flush()


@pytest.mark.asyncio
async def test_unknown_state_is_rejected_by_the_database(session):
    """The open-command index hard-codes ``state = 'requested'``, as persist's does."""
    source = await _source(session)
    session.add(_command(source, "captured"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_a_new_command_records_what_was_sent_and_nothing_else(session):
    source = await _source(session)
    user = AppUser(external_id="ext-380", email="op@example.com")
    session.add(user)
    await session.flush()
    wait = {"kind": "selector", "selector": "#main", "seconds": None}
    row = _command(source, requested_by=user.id, wait=wait, full_page=False)
    session.add(row)
    await session.commit()

    got = await session.get(CaptureCommand, row.command_id)
    assert (got.viewport_width, got.viewport_height, got.full_page) == (1280, 800, False)
    assert got.wait == wait
    assert got.requested_by == user.id
    assert got.issued_at == T0
    # The outcome columns stay empty until a fact lands.
    for column in (
        "reason",
        "detail",
        "status_code",
        "terminal",
        "content_fingerprint",
        "blob_uri",
        "media_type",
        "size_bytes",
        "image_width",
        "image_height",
        "final_url",
        "captured_at",
        "blob_expires_at",
        "closed_at",
        "last_fact_at",
        "persisted_at",
    ):
        assert getattr(got, column) is None, column


@pytest.mark.asyncio
async def test_deleting_the_source_deletes_its_commands(session):
    source = await _source(session)
    row = _command(source)
    session.add(row)
    await session.commit()

    await session.execute(
        delete(InfoSource).where(InfoSource.info_source_id == source.info_source_id)
    )
    await session.commit()

    left = await session.execute(
        select(CaptureCommand).where(CaptureCommand.command_id == row.command_id)
    )
    assert left.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_deleting_the_operator_keeps_the_command(session):
    """History outlives the operator: ``requested_by`` is SET NULL."""
    source = await _source(session)
    user = AppUser(external_id="ext-380-gone", email="gone@example.com")
    session.add(user)
    await session.flush()
    row = _command(source, requested_by=user.id)
    command_id = row.command_id
    session.add(row)
    await session.commit()

    await session.execute(delete(AppUser).where(AppUser.id == user.id))
    await session.commit()
    session.expire_all()

    got = await session.get(CaptureCommand, command_id)
    assert got is not None
    assert got.requested_by is None
