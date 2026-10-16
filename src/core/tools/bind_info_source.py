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


async def bind_info_source(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    info_source_id: ULID,
) -> InfoItemSource:
    """Persist a new ``info_item_sources`` row.

    Validates that both the InfoItem and InfoSource exist, and that no active
    binding already exists for this InfoItem. Locks the InfoItem row first, as
    ``swap_primary_source`` does: unlocked, a bind racing a swap on an item with
    no primary sees none, and its insert collides on
    ``uq_info_item_sources_active`` (a 500) instead of refusing. Caller commits.
    """
    item = await lock_info_item(db, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    source = await db.get(InfoSource, info_source_id)
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

    binding = InfoItemSource(
        info_item_id=info_item_id,
        info_source_id=info_source_id,
    )
    db.add(binding)
    await db.flush()
    return binding


def emit_primary_changed(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    old_info_source_id: ULID | None,
    new_info_source_id: ULID,
) -> None:
    """Stage an ``info_item_primary_changed`` outbox row on ``info.changes``.

    Every new active binding is a primary binding, so every one emits this;
    ``old_info_source_id`` is ``None`` on first assignment. Caller commits.
    """
    event = InfoItemPrimaryChangedEmit(
        occurred_at=datetime.now(UTC),
        info_item_id=str(info_item_id),
        old_info_source_id=str(old_info_source_id) if old_info_source_id is not None else None,
        new_info_source_id=str(new_info_source_id),
    )
    db.add(ChangesOutboxRow(topic="info.changes", payload=event.model_dump(mode="json")))
