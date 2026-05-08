"""bind_revision — pin an InfoItem to a SourceRevision (idempotent)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItem, InfoItemSourceRevision, SourceRevision


class BindError(Exception):
    """Base class for bind_revision failures."""


class InfoItemNotFoundError(BindError):
    """The given info_item_id does not exist."""


class SourceRevisionNotFoundError(BindError):
    """The given source_revision_id does not exist."""


async def bind_revision(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    source_revision_id: ULID,
    bound_at: datetime | None = None,
) -> InfoItemSourceRevision:
    """Insert an InfoItemSourceRevision row idempotently.

    If a row for (info_item_id, source_revision_id) already exists, return it
    unchanged. Otherwise insert with bound_at = bound_at or now().

    Caller is responsible for committing.
    """
    item = await db.get(InfoItem, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    rev = await db.get(SourceRevision, source_revision_id)
    if rev is None:
        raise SourceRevisionNotFoundError(str(source_revision_id))

    existing = await db.get(
        InfoItemSourceRevision,
        {"info_item_id": info_item_id, "source_revision_id": source_revision_id},
    )
    if existing is not None:
        return existing

    binding = InfoItemSourceRevision(
        info_item_id=info_item_id,
        source_revision_id=source_revision_id,
        bound_at=bound_at or datetime.now(UTC),
    )
    db.add(binding)
    await db.flush()
    return binding
