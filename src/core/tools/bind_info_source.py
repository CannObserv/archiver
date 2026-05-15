"""Bind an InfoSource to an InfoItem with cross-table shape/root validation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItem, InfoItemSource, InfoSource


class InfoItemNotFoundError(Exception):
    """The given info_item_id does not reference an InfoItem."""


class InfoSourceNotFoundError(Exception):
    """The given info_source_id does not reference an InfoSource."""


class RoleShapeMismatchError(Exception):
    """role/shape combination is invalid.

    NULL role requires a root-shaped InfoSource (URL non-null).
    Fragment role requires a fragment-shaped InfoSource (parent non-null).
    """

    def __init__(self, *, role: str | None, source_is_root: bool):
        self.role = role
        self.source_is_root = source_is_root
        super().__init__(
            f"role={role!r} is not valid for "
            f"{'root' if source_is_root else 'fragment'}-shaped InfoSource"
        )


class ActiveRootMissingError(Exception):
    """Tried to bind a fragment-role InfoSource before any active root binding exists."""


class FragmentParentMismatchError(Exception):
    """Fragment's parent_info_source_id does not match the InfoItem's active root binding."""

    def __init__(self, *, expected_root_id: ULID, actual_parent_id: ULID):
        self.expected_root_id = expected_root_id
        self.actual_parent_id = actual_parent_id
        super().__init__(
            f"fragment's parent {actual_parent_id} != active root binding's source "
            f"{expected_root_id}"
        )


async def bind_info_source(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    info_source_id: ULID,
    role: str | None,
) -> InfoItemSource:
    """Persist a new ``info_item_sources`` row after validating shape + root invariants.

    Caller commits.
    """
    item = await db.get(InfoItem, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    source = await db.get(InfoSource, info_source_id)
    if source is None:
        raise InfoSourceNotFoundError(str(info_source_id))

    source_is_root = source.parent_info_source_id is None

    # 1. Shape consistency
    if role is None and not source_is_root:
        raise RoleShapeMismatchError(role=role, source_is_root=False)
    if role is not None and source_is_root:
        raise RoleShapeMismatchError(role=role, source_is_root=True)

    # 2. Fragment-shares-root: fragment's parent must equal the InfoItem's
    # currently-active NULL-role binding's info_source_id.
    if not source_is_root:
        active_root_id = await db.scalar(
            select(InfoItemSource.info_source_id).where(
                InfoItemSource.info_item_id == info_item_id,
                InfoItemSource.role.is_(None),
                InfoItemSource.deactivated_at.is_(None),
            )
        )
        if active_root_id is None:
            raise ActiveRootMissingError(str(info_item_id))
        if active_root_id != source.parent_info_source_id:
            raise FragmentParentMismatchError(
                expected_root_id=active_root_id,
                actual_parent_id=source.parent_info_source_id,
            )

    binding = InfoItemSource(
        info_item_id=info_item_id,
        info_source_id=info_source_id,
        role=role,
    )
    db.add(binding)
    await db.flush()
    return binding
