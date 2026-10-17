"""Replace an InfoItem's primary InfoSource in one mutation flow (archiver#45).

Deactivating the old binding and binding the new one are two writes but one
change: the swap announces **once**, with the final state. Done as two flows
(``DELETE`` then ``POST``) it announces revoked and then live, and the consumer
destroys its row and recreates it, losing every local column.

**A revert starts a new tenure.** Each binding row is one tenure, keyed by its
own ``id`` (archiver#392), so swapping back to a previous primary inserts a row
and the first tenure keeps its ``created_at`` and ``deactivated_at``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItemSource, InfoSource
from src.core.services.registry_announcement import announce_info_item
from src.core.tools.bind_info_source import (
    InfoItemNotFoundError,
    InfoSourceNotFoundError,
    emit_primary_changed,
)
from src.core.tools.rep_fields_gate import lock_info_item

__all__ = [
    "InfoItemNotFoundError",
    "InfoSourceNotFoundError",
    "SwapResult",
    "swap_primary_source",
]


@dataclass(frozen=True)
class SwapResult:
    """The active binding after the swap, and the primary before the call.

    ``previous_info_source_id`` is the active primary when the call began, and
    ``None`` when the item had none (the API's 201). On a no-op it is the
    requested source itself, since that was already the primary.
    ``changed`` is false on that no-op: nothing was written, emitted or announced.
    """

    binding: InfoItemSource
    previous_info_source_id: ULID | None
    changed: bool


async def swap_primary_source(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    info_source_id: ULID,
) -> SwapResult:
    """Make ``info_source_id`` the item's primary, retiring the current one.

    Locks the InfoItem row first, so two concurrent swaps serialize instead of
    both deactivating the same binding and colliding on
    ``uq_info_item_sources_active``. Always inserts a new tenure.
    Emits ``info_item_primary_changed`` and announces once. Caller commits.
    """
    if await lock_info_item(db, info_item_id) is None:
        raise InfoItemNotFoundError(str(info_item_id))
    if await db.get(InfoSource, info_source_id) is None:
        raise InfoSourceNotFoundError(str(info_source_id))

    current = (
        await db.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if current is not None and current.info_source_id == info_source_id:
        return SwapResult(binding=current, previous_info_source_id=info_source_id, changed=False)

    previous_info_source_id = None
    if current is not None:
        previous_info_source_id = current.info_source_id
        current.deactivated_at = datetime.now(UTC)
        # The partial unique index admits the new primary only once the old one is out.
        await db.flush()

    binding = InfoItemSource(info_item_id=info_item_id, info_source_id=info_source_id)
    db.add(binding)
    await db.flush()

    emit_primary_changed(
        db,
        info_item_id=info_item_id,
        old_info_source_id=previous_info_source_id,
        new_info_source_id=info_source_id,
    )
    await announce_info_item(db, info_item_id)
    return SwapResult(
        binding=binding, previous_info_source_id=previous_info_source_id, changed=True
    )
