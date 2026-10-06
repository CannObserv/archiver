"""``pm_organizations``: the local snapshot every effective bag reads (archiver#304).

Written by the link (``link_org``) and, from archiver#305, the follower - both
through ``apply_org_snapshot``, so a rename is recorded the same way whichever
of them sees it first. Read through ``load_org_values``, which is how rendering
gets an org without ever calling Power Map.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.core.models import InfoItem, PmOrganization
from src.core.power_map.client import OrgSnapshot
from src.core.rep_fields import OrgValues

logger = get_logger(__name__)


class OrgUnnamedError(Exception):
    """The Power Map org has no canonical name, so it cannot supply ``org.title``."""

    def __init__(self, pm_org_id: str) -> None:
        self.pm_org_id = pm_org_id
        super().__init__(f"Power Map org {pm_org_id} has no canonical name")


async def apply_org_snapshot(
    db: AsyncSession, org: OrgSnapshot, *, now: datetime
) -> PmOrganization:
    """Upsert one org's snapshot and return the row, locked ``FOR UPDATE``.

    Insert-if-absent then lock, so two links of a new org cannot both insert. A
    changed ``name`` or ``acronym`` sets ``renamed_from`` (the previous name)
    and ``renamed_at`` and logs ``pm_org_renamed`` at WARNING: every item linked
    to the org renders the new path from its next occasion (Q4, no
    confirmation). An answer clears ``missing_since``. Flushes, does not commit.

    Raises:
        OrgUnnamedError: ``org.name`` is ``None``; nothing is written.
    """
    if org.name is None:
        raise OrgUnnamedError(org.pm_org_id)
    values = {
        "name": org.name,
        "acronym": org.acronym,
        "archived_at": org.archived_at,
        "active": org.active,
        "succeeded_by": org.succeeded_by,
        "etag": org.etag,
        "pm_updated_at": org.pm_updated_at,
    }
    await db.execute(
        pg_insert(PmOrganization)
        .values(pm_org_id=org.pm_org_id, checked_at=now, **values)
        .on_conflict_do_nothing(index_elements=["pm_org_id"])
    )
    row = await db.get(PmOrganization, org.pm_org_id, with_for_update=True, populate_existing=True)
    assert row is not None  # inserted above, and rows are never deleted while linked
    if (row.name, row.acronym) != (org.name, org.acronym):
        logger.warning(
            "pm_org_renamed",
            extra={
                "pm_org_id": org.pm_org_id,
                "before": {"name": row.name, "acronym": row.acronym},
                "after": {"name": org.name, "acronym": org.acronym},
            },
        )
        row.renamed_from = row.name
        row.renamed_at = now
    for column, value in values.items():
        setattr(row, column, value)
    row.checked_at = now
    row.missing_since = None
    await db.flush()
    return row


def org_values(row: PmOrganization | None) -> OrgValues | None:
    """The snapshot as the effective bag reads it, or ``None`` for no row."""
    if row is None:
        return None
    return OrgValues(name=row.name, acronym=row.acronym)


async def load_org_values(db: AsyncSession, item: InfoItem) -> OrgValues | None:
    """The item's linked org as ``OrgValues``, or ``None`` when unlinked."""
    if item.pm_org_id is None:
        return None
    return org_values(await db.get(PmOrganization, item.pm_org_id))


async def load_orgs(db: AsyncSession, items: Iterable[InfoItem]) -> dict[str, PmOrganization]:
    """The snapshot rows the items link, keyed by ``pm_org_id``, in one query."""
    ids = {item.pm_org_id for item in items if item.pm_org_id is not None}
    if not ids:
        return {}
    rows = await db.execute(select(PmOrganization).where(PmOrganization.pm_org_id.in_(ids)))
    return {row.pm_org_id: row for row in rows.scalars()}
