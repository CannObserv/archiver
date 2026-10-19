"""Bind an InfoSource to an InfoItem."""

from datetime import UTC, datetime

from co_core.pure.models.changes import InfoItemPrimaryChangedEmit
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import ChangesOutboxRow, InfoItemSource, InfoSource
from src.core.tools.rep_fields_gate import lock_info_item


class InfoItemNotFoundError(Exception):
    """The given info_item_id does not reference an InfoItem."""


class InfoSourceNotFoundError(Exception):
    """The given info_source_id does not reference an InfoSource."""


class ActiveBindingAlreadyExistsError(Exception):
    """An active binding already exists for this InfoItem.

    Deactivate it via ``DELETE /info-items/{id}/info-sources/{source_id}``
    first, then re-POST.
    """

    def __init__(self, *, existing_info_source_id: ULID):
        self.existing_info_source_id = existing_info_source_id
        super().__init__(
            f"an active binding already exists for info_source_id {existing_info_source_id!s}"
        )


class InfoSourceAlreadyBoundError(Exception):
    """``require_unbound_source`` was set and the source backs an active item.

    Registration's Case B reuse (archiver#51) only takes a source no item
    holds; one bound since the URL check is a conflict, not a share.
    """

    def __init__(self, *, info_item_ids: list[ULID]):
        self.info_item_ids = info_item_ids
        super().__init__(f"info source already bound to {', '.join(map(str, info_item_ids))}")


async def bind_info_source(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    info_source_id: ULID,
    require_unbound_source: bool = False,
) -> InfoItemSource:
    """Persist a new ``info_item_sources`` row and emit ``info_item_primary_changed``.

    The only writer of a binding row (archiver#390, guarded by
    ``tests/core/test_binding_guard.py``): every new active binding emits, so
    no bind path can forget to. ``old_info_source_id`` is the item's latest
    closed tenure, ``None`` when it has never had one.

    Validates that both the InfoItem and InfoSource exist, and that no active
    binding already exists for this InfoItem. Locks the InfoItem row first, as
    ``swap_primary_source`` does: unlocked, a bind racing a swap on an item with
    no primary sees none, and its insert collides on
    ``uq_info_item_sources_active`` (a 500) instead of refusing. Does not
    announce: callers announce once their whole change is staged. Caller commits.

    Then locks the InfoSource row, so two binds of one source serialize: a
    Case B item is new, and its own lock guards nothing (archiver#51). ``FOR
    NO KEY UPDATE``, because a ``source_revisions`` insert takes ``FOR KEY
    SHARE`` on its source through the FK, and ``FOR UPDATE`` would stall
    ingest for the source while the bind is open. With
    ``require_unbound_source``, a source any item actively holds is refused
    with ``InfoSourceAlreadyBoundError``; without it, sharing stays allowed.
    """
    item = await lock_info_item(db, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    source = await db.get(
        InfoSource, info_source_id, with_for_update={"key_share": True}, populate_existing=True
    )
    if source is None:
        raise InfoSourceNotFoundError(str(info_source_id))

    existing = (
        await db.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ActiveBindingAlreadyExistsError(existing_info_source_id=existing.info_source_id)

    if require_unbound_source:
        holders = list(
            (
                await db.execute(
                    select(InfoItemSource.info_item_id).where(
                        InfoItemSource.info_source_id == info_source_id,
                        InfoItemSource.deactivated_at.is_(None),
                    )
                )
            ).scalars()
        )
        if holders:
            raise InfoSourceAlreadyBoundError(info_item_ids=holders)

    binding = InfoItemSource(
        info_item_id=info_item_id,
        info_source_id=info_source_id,
    )
    db.add(binding)
    await db.flush()

    previous = (
        await db.execute(
            select(InfoItemSource)
            .where(
                InfoItemSource.info_item_id == info_item_id,
                InfoItemSource.deactivated_at.isnot(None),
            )
            # Tenure ids are time-ordered ULIDs: an equal close time goes to the later one.
            .order_by(InfoItemSource.deactivated_at.desc(), InfoItemSource.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    emit_primary_changed(
        db,
        info_item_id=info_item_id,
        old_info_source_id=previous.info_source_id if previous is not None else None,
        new_info_source_id=info_source_id,
    )
    return binding


def emit_primary_changed(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    old_info_source_id: ULID | None,
    new_info_source_id: ULID,
) -> None:
    """Stage an ``info_item_primary_changed`` outbox row on ``info.changes``.

    Called only by ``bind_info_source``, once per new binding: a second caller
    would emit twice, and ``tests/core/test_binding_guard.py`` refuses one.
    ``old_info_source_id`` is ``None`` on first assignment. Caller commits.
    """
    event = InfoItemPrimaryChangedEmit(
        occurred_at=datetime.now(UTC),
        info_item_id=str(info_item_id),
        old_info_source_id=str(old_info_source_id) if old_info_source_id is not None else None,
        new_info_source_id=str(new_info_source_id),
    )
    db.add(ChangesOutboxRow(topic="info.changes", payload=event.model_dump(mode="json")))
