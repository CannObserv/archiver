"""Bind an InfoSource to an InfoItem with cross-table shape/root validation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import FragmentRole, InfoItem, InfoItemSource, InfoSource
from src.core.source_spec_schema.families import Family, family_for


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


class ActiveRootAlreadyExistsError(Exception):
    """A NULL-role (primary) binding was requested but one is already active.

    Deactivate the existing primary via
    ``DELETE /info-items/{id}/info-sources/{source_id}`` first, then re-POST.
    """

    def __init__(self, *, existing_info_source_id: ULID):
        self.existing_info_source_id = existing_info_source_id
        super().__init__(
            f"an active primary binding already exists for info_source_id "
            f"{existing_info_source_id!s}"
        )


class AlgorithmFamilyMismatchError(Exception):
    """Fragment's extraction algorithm belongs to a different content-kind
    family than the InfoItem's active root binding's algorithm.

    Every fragment's extraction runs against the root's fetched bytes (the
    "InfoItem = fetch group" invariant; see
    ``src/core/source_spec_schema/v1.json`` description). A jsonpath
    selector evaluated against HTML bytes silently misextracts, and
    vice-versa — hence the bind-time rejection.
    """

    def __init__(self, *, expected_family: Family, actual_algorithm: str):
        self.expected_family = expected_family
        self.actual_algorithm = actual_algorithm
        super().__init__(
            f"fragment algorithm {actual_algorithm!r} does not match the "
            f"InfoItem's primary algorithm family {expected_family!r}"
        )


async def bind_info_source(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    info_source_id: ULID,
    role: FragmentRole | None,
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

    # 1b. Collision guard: reject a second active primary.
    if role is None:
        existing_binding = (
            await db.execute(
                select(InfoItemSource).where(
                    InfoItemSource.info_item_id == info_item_id,
                    InfoItemSource.role.is_(None),
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_binding is not None:
            raise ActiveRootAlreadyExistsError(
                existing_info_source_id=existing_binding.info_source_id
            )

    # 2. Fragment-shares-root: fragment's parent must equal the InfoItem's
    # currently-active NULL-role binding's info_source_id.
    if not source_is_root:
        active_root = (
            await db.execute(
                select(InfoSource)
                .join(
                    InfoItemSource,
                    InfoItemSource.info_source_id == InfoSource.info_source_id,
                )
                .where(
                    InfoItemSource.info_item_id == info_item_id,
                    InfoItemSource.role.is_(None),
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active_root is None:
            raise ActiveRootMissingError(str(info_item_id))
        if active_root.info_source_id != source.parent_info_source_id:
            raise FragmentParentMismatchError(
                expected_root_id=active_root.info_source_id,
                actual_parent_id=source.parent_info_source_id,
            )

        # 3. Algorithm-family compatibility (archiver#22). The active root's
        # algorithm establishes the fetch group's content kind; this fragment
        # must agree.
        expected_family = family_for(active_root.source_spec["extraction"]["algorithm"])
        actual_algorithm = source.source_spec["extraction"]["algorithm"]
        if family_for(actual_algorithm) != expected_family:
            raise AlgorithmFamilyMismatchError(
                expected_family=expected_family,
                actual_algorithm=actual_algorithm,
            )

    binding = InfoItemSource(
        info_item_id=info_item_id,
        info_source_id=info_source_id,
        role=role,
    )
    db.add(binding)
    await db.flush()
    return binding
