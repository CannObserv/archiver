"""Tests for the ``info.watch-status`` apply service (archiver#151).

The service is the write half of the tail consumer: last-write-wins upsert of
the ``watch_status`` cache, tombstone purge, the durable
``info_sources.last_observed_at`` write-through with its two guards, and the
per-stream resume cursor.

Covers:
1. A live status → cache row upserted with every field
2. A second message for the same item → row overwritten (LWW), not duplicated
3. A tombstone → cache row deleted; repeated tombstone is an idempotent no-op
4. A live message after a tombstone → row recreated (stream order wins)
5. Unknown info_item_id → dropped, nothing written
6. Malformed info_item_id → dropped, nothing written
7. last_observed_at writes through to the active primary source
8. Write-through is monotonic — an older observation never regresses it
9. Write-through skips when the active binding postdates the observation
10. Write-through targets only the *active* binding, not deactivated ones
11. A no-change cycle advances info_sources.last_observed_at while leaving
    source_revisions untouched (the issue's distinguishing property)
12. Cursor: absent → None; advance persists; advance overwrites
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from co_core.pure.models.changes import WatchStatusState
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import (
    InfoItem,
    InfoItemSource,
    InfoSource,
    SourceRevision,
    WatchStatus,
)
from src.core.services.watch_status import (
    WATCH_STATUS_TOPIC,
    advance_cursor,
    apply_watch_status,
    read_cursor,
)

T0 = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def make_status(item_id: str, **overrides) -> WatchStatusState:
    defaults = dict(
        occurred_at=T0,
        info_item_id=item_id,
        applied_generation=3,
        applied_active=True,
        applied_interval="1d",
        last_attempt_at=T0 - timedelta(minutes=5),
        last_observed_at=T0 - timedelta(minutes=5),
        health="ok",
    )
    defaults.update(overrides)
    return WatchStatusState(**defaults)


async def make_item(session: AsyncSession, *, with_source: bool = True) -> InfoItem:
    item = InfoItem(name="Watched thing")
    session.add(item)
    await session.flush()
    if with_source:
        source = InfoSource(url="https://example.gov/rules", source_specs=[{"k": "v"}])
        session.add(source)
        await session.flush()
        session.add(
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=source.info_source_id,
                created_at=T0 - timedelta(days=30),
            )
        )
    await session.commit()
    return item


async def get_row(session: AsyncSession, item_id) -> WatchStatus | None:
    return (
        await session.execute(select(WatchStatus).where(WatchStatus.info_item_id == item_id))
    ).scalar_one_or_none()


async def get_source(session: AsyncSession, item_id) -> InfoSource:
    return (
        await session.execute(
            select(InfoSource)
            .join(InfoItemSource, InfoItemSource.info_source_id == InfoSource.info_source_id)
            .where(InfoItemSource.info_item_id == item_id)
        )
    ).scalar_one()


class TestApply:
    async def test_live_status_upserts_every_field(self, session: AsyncSession):
        item = await make_item(session)
        state = make_status(str(item.info_item_id))

        disposition = await apply_watch_status(session, state)
        await session.commit()

        assert disposition == "applied"
        row = await get_row(session, item.info_item_id)
        assert row is not None
        assert row.applied_generation == 3
        assert row.applied_active is True
        assert row.applied_interval == "1d"
        assert row.last_attempt_at == T0 - timedelta(minutes=5)
        assert row.last_observed_at == T0 - timedelta(minutes=5)
        assert row.health == "ok"
        assert row.occurred_at == T0

    async def test_second_message_overwrites_lww(self, session: AsyncSession):
        item = await make_item(session)
        await apply_watch_status(session, make_status(str(item.info_item_id)))
        await session.commit()

        later = make_status(
            str(item.info_item_id),
            occurred_at=T0 + timedelta(minutes=10),
            applied_generation=4,
            applied_active=False,
            health="error",
            applied_interval=None,
        )
        await apply_watch_status(session, later)
        await session.commit()

        count = (await session.execute(select(func.count()).select_from(WatchStatus))).scalar_one()
        assert count == 1
        row = await get_row(session, item.info_item_id)
        assert row.applied_generation == 4
        assert row.applied_active is False
        assert row.health == "error"
        assert row.applied_interval is None

    async def test_tombstone_deletes_and_is_idempotent(self, session: AsyncSession):
        item = await make_item(session)
        await apply_watch_status(session, make_status(str(item.info_item_id)))
        await session.commit()

        tomb = make_status(
            str(item.info_item_id),
            revoked=True,
            applied_active=None,
            health=None,
            last_attempt_at=None,
            last_observed_at=None,
            applied_interval=None,
        )
        assert await apply_watch_status(session, tomb) == "revoked"
        await session.commit()
        assert await get_row(session, item.info_item_id) is None

        # Republished tombstone: no error, still nothing.
        assert await apply_watch_status(session, tomb) == "revoked"
        await session.commit()
        assert await get_row(session, item.info_item_id) is None

    async def test_live_after_tombstone_recreates(self, session: AsyncSession):
        item = await make_item(session)
        tomb = make_status(str(item.info_item_id), revoked=True, applied_active=None)
        await apply_watch_status(session, tomb)
        await session.commit()

        await apply_watch_status(session, make_status(str(item.info_item_id), applied_generation=9))
        await session.commit()
        row = await get_row(session, item.info_item_id)
        assert row is not None
        assert row.applied_generation == 9

    async def test_unknown_item_dropped(self, session: AsyncSession):
        state = make_status("01K2E0FAKEFAKEFAKEFAKEFAKE")
        assert await apply_watch_status(session, state) == "unknown_item"
        await session.commit()
        count = (await session.execute(select(func.count()).select_from(WatchStatus))).scalar_one()
        assert count == 0

    async def test_malformed_item_id_dropped(self, session: AsyncSession):
        state = make_status("not-a-ulid")
        assert await apply_watch_status(session, state) == "invalid_id"


class TestObservationWriteThrough:
    async def test_stamps_active_source(self, session: AsyncSession):
        item = await make_item(session)
        observed = T0 - timedelta(minutes=5)
        await apply_watch_status(
            session, make_status(str(item.info_item_id), last_observed_at=observed)
        )
        await session.commit()
        source = await get_source(session, item.info_item_id)
        assert source.last_observed_at == observed

    async def test_monotonic_never_regresses(self, session: AsyncSession):
        item = await make_item(session)
        newer = T0 - timedelta(minutes=5)
        await apply_watch_status(
            session, make_status(str(item.info_item_id), last_observed_at=newer)
        )
        await session.commit()

        older = T0 - timedelta(hours=6)
        await apply_watch_status(
            session,
            make_status(
                str(item.info_item_id),
                occurred_at=T0 + timedelta(minutes=1),
                last_observed_at=older,
            ),
        )
        await session.commit()
        source = await get_source(session, item.info_item_id)
        assert source.last_observed_at == newer

    async def test_skips_when_binding_postdates_observation(self, session: AsyncSession):
        """A rebind after the observation: the stamp says nothing about the new source."""
        item = await make_item(session, with_source=False)
        source = InfoSource(url="https://example.gov/new", source_specs=[{"k": "v"}])
        session.add(source)
        await session.flush()
        session.add(
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=source.info_source_id,
                created_at=T0,  # bound at T0 …
            )
        )
        await session.commit()

        await apply_watch_status(
            session,
            make_status(
                str(item.info_item_id),
                last_observed_at=T0 - timedelta(hours=1),  # … observed before T0
            ),
        )
        await session.commit()
        source = await get_source(session, item.info_item_id)
        assert source.last_observed_at is None
        # The cache row itself still records the reported value.
        row = await get_row(session, item.info_item_id)
        assert row.last_observed_at == T0 - timedelta(hours=1)

    async def test_ignores_deactivated_binding(self, session: AsyncSession):
        item = await make_item(session)  # active binding
        old_source = InfoSource(url="https://example.gov/old", source_specs=[{"k": "v"}])
        session.add(old_source)
        await session.flush()
        session.add(
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=old_source.info_source_id,
                created_at=T0 - timedelta(days=90),
                deactivated_at=T0 - timedelta(days=60),
            )
        )
        await session.commit()

        await apply_watch_status(session, make_status(str(item.info_item_id)))
        await session.commit()

        await session.refresh(old_source)
        assert old_source.last_observed_at is None

    async def test_no_change_cycle_advances_without_touching_revisions(self, session: AsyncSession):
        """The issue's distinguishing property: verified-current ≠ changed."""
        item = await make_item(session)
        source = await get_source(session, item.info_item_id)
        rev = SourceRevision(
            info_source_id=source.info_source_id,
            content_fingerprint="sha256:" + "b" * 64,
            captured_at=T0 - timedelta(days=3),
        )
        session.add(rev)
        await session.commit()
        rev_id = rev.source_revision_id

        await apply_watch_status(
            session,
            make_status(str(item.info_item_id), last_observed_at=T0 - timedelta(minutes=1)),
        )
        await session.commit()

        source = await get_source(session, item.info_item_id)
        assert source.last_observed_at == T0 - timedelta(minutes=1)
        revisions = (
            (
                await session.execute(
                    select(SourceRevision).where(
                        SourceRevision.info_source_id == source.info_source_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [r.source_revision_id for r in revisions] == [rev_id]
        assert revisions[0].captured_at == T0 - timedelta(days=3)

    async def test_absent_observation_stamps_nothing(self, session: AsyncSession):
        item = await make_item(session)
        await apply_watch_status(
            session, make_status(str(item.info_item_id), last_observed_at=None)
        )
        await session.commit()
        source = await get_source(session, item.info_item_id)
        assert source.last_observed_at is None


class TestCursor:
    async def test_absent_cursor_is_none(self, session: AsyncSession):
        assert await read_cursor(session, WATCH_STATUS_TOPIC) is None

    async def test_advance_persists_and_overwrites(self, session: AsyncSession):
        await advance_cursor(session, WATCH_STATUS_TOPIC, "1700000000000-0")
        await session.commit()
        assert await read_cursor(session, WATCH_STATUS_TOPIC) == "1700000000000-0"

        await advance_cursor(session, WATCH_STATUS_TOPIC, "1700000000001-5")
        await session.commit()
        assert await read_cursor(session, WATCH_STATUS_TOPIC) == "1700000000001-5"
