"""The capture issuers' source-row lock never waits on a revision insert (archiver#380 C).

``record_revision`` inserts a revision, whose foreign key takes ``FOR KEY SHARE``
on the source row, and then issues a capture under the source lock. ``FOR UPDATE``
conflicts with another transaction's ``KEY SHARE``, so two writers for one
source would each hold one and wait on the other's: a deadlock. ``FOR NO KEY
UPDATE`` conflicts only with itself and stronger, which still serializes the
issuers' one-open check and leaves revision inserts free.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import ChangesOutboxRow, InfoSource, SourceRevision
from src.core.services.capture import ENABLED_ENV, CaptureAlreadyOpen, request_capture

ON = {ENABLED_ENV: "1"}


@pytest.fixture
async def committed_source(test_engine):
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with factory() as s:
        source = InfoSource(url="https://example.com/lock-probe", source_specs=[])
        s.add(source)
        await s.commit()
    yield factory, source
    # Committed rows outlive the per-test rollback: the source cascades to its
    # capture_commands, but the outbox row is keyed only in its payload.
    async with factory() as s:
        await s.execute(
            delete(ChangesOutboxRow).where(
                ChangesOutboxRow.payload["info_source_id"].astext == str(source.info_source_id)
            )
        )
        await s.execute(
            delete(InfoSource).where(InfoSource.info_source_id == source.info_source_id)
        )
        await s.commit()


@pytest.mark.asyncio
async def test_a_click_does_not_wait_on_an_uncommitted_revision_insert(committed_source):
    factory, source = committed_source
    async with factory() as inserting, factory() as clicking:
        inserting.add(
            SourceRevision(
                info_source_id=source.info_source_id,
                content_fingerprint="sha256:" + "f" * 64,
                captured_at=datetime.now(UTC),
            )
        )
        await inserting.flush()  # holds FOR KEY SHARE on the source row
        await clicking.execute(text("SET LOCAL lock_timeout = '2s'"))

        command = await request_capture(
            clicking, source.info_source_id, requested_by=None, environ=ON
        )

        assert command.state == "requested"
        await clicking.rollback()
        await inserting.rollback()


@pytest.mark.asyncio
async def test_two_issuers_for_one_source_still_serialize(committed_source):
    """The weaker lock still conflicts with itself: the second click waits, then is refused."""
    factory, source = committed_source
    async with factory() as first, factory() as second:
        await request_capture(first, source.info_source_id, requested_by=None, environ=ON)
        await second.execute(text("SET LOCAL lock_timeout = '500ms'"))

        with pytest.raises(Exception, match="lock timeout"):
            await request_capture(second, source.info_source_id, requested_by=None, environ=ON)
        await second.rollback()

        await first.commit()
        async with factory() as third:
            with pytest.raises(CaptureAlreadyOpen):
                await request_capture(third, source.info_source_id, requested_by=None, environ=ON)
