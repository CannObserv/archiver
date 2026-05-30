"""Deactivate an InfoItemSource binding (sets deactivated_at)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItemSource


class BindingNotFoundError(Exception):
    """No active InfoItemSource binding found for the given item/source pair."""

    def __init__(self, *, info_item_id: ULID, info_source_id: ULID):
        self.info_item_id = info_item_id
        self.info_source_id = info_source_id
        super().__init__(
            f"no active binding for info_item_id={info_item_id!s} info_source_id={info_source_id!s}"
        )


async def deactivate_info_item_source_binding(
    session: AsyncSession,
    *,
    info_item_id: ULID,
    info_source_id: ULID,
) -> InfoItemSource:
    """Set ``deactivated_at`` on an active ``info_item_sources`` row.

    Raises ``BindingNotFoundError`` when no active binding exists for the pair.
    Caller commits.
    """
    result = await session.execute(
        select(InfoItemSource).where(
            InfoItemSource.info_item_id == info_item_id,
            InfoItemSource.info_source_id == info_source_id,
            InfoItemSource.deactivated_at.is_(None),
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise BindingNotFoundError(info_item_id=info_item_id, info_source_id=info_source_id)
    binding.deactivated_at = datetime.now(UTC)
    await session.flush()
    return binding
