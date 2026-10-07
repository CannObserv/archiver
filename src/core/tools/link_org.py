"""link_org — link an InfoItem to a Power Map org, or unlink it (archiver#304).

``PUT /info-items/{id}/org`` calls it, and the dashboard's Organization row
(archiver#306) will. Power Map is fetched first, outside any lock - an HTTP
round trip must not hold the InfoItem row - then, under that row's lock (the
one every writer of the effective bag takes, ``rep_fields_gate``):

1. upsert the org's ``pm_organizations`` snapshot
2. rewrite the stored bag: a link drops ``org.title``/``org.acronym``, which
   the org now supplies; an unlink writes the org's values back in, so the
   effective bag and every path stay put
3. check every active assignment against the new effective bag, and refuse a
   change that moves one's path unless the caller allows it - #302's move
   contract, the same refusal a bag save gives
4. set ``info_items.pm_org_id``

Flushes, does not commit: the caller owns the transaction. Power Map is never
called during replication; rendering reads the snapshot written in step 1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import InfoItem
from src.core.power_map import Merged, OrgResult, OrgSnapshot, Snapshot
from src.core.power_map.snapshots import apply_org_snapshot, load_org_values, org_values
from src.core.rep_fields import with_org_values, without_org_owned_keys
from src.core.tools.assign_rep_spec import InfoItemNotFoundError
from src.core.tools.rep_fields_gate import lock_info_item
from src.core.tools.set_rep_fields import (
    RepFieldsMoveError,
    RepFieldsRefusedError,
    active_assignments,
    assignment_refusals,
    destination_moves,
    log_moves,
)

logger = get_logger(__name__)


class PowerMapReader(Protocol):
    """What linking needs from Power Map: ``PowerMapClient``, or a test's fake."""

    async def get_org(self, pm_org_id: str, etag: str | None = None) -> OrgResult: ...


class PowerMapNotConfiguredError(Exception):
    """``ARCHIVER_POWER_MAP_API_KEY`` is unset, so there is no Power Map to link from."""

    def __init__(self) -> None:
        super().__init__("Power Map not configured")


class OrgNotFoundError(Exception):
    """Power Map has no such org: unknown, deleted, or merged into one that is gone."""

    def __init__(self, pm_org_id: str) -> None:
        self.pm_org_id = pm_org_id
        super().__init__(f"Power Map org {pm_org_id} not found")


async def fetch_linkable_org(power_map: PowerMapReader | None, pm_org_id: str) -> OrgSnapshot:
    """The org to link for ``pm_org_id``, following a merge to its winner.

    One hop is enough: Power Map's ``merged_into`` is already the chain's live
    end (power-map#607).

    Raises:
        PowerMapNotConfiguredError: ``power_map`` is ``None``.
        PowerMapUnavailableError: no answer from Power Map.
        OrgNotFoundError: Power Map has no such org.
    """
    if power_map is None:
        raise PowerMapNotConfiguredError()
    result = await power_map.get_org(pm_org_id)
    if isinstance(result, Merged):
        logger.info(
            "Linking a merged Power Map org's winner",
            extra={"pm_org_id": pm_org_id, "winner": result.winner},
        )
        result = await power_map.get_org(result.winner)
    if not isinstance(result, Snapshot):
        raise OrgNotFoundError(pm_org_id)
    return result.org


async def link_org(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    pm_org_id: str | None,
    power_map: PowerMapReader | None,
    allow_destination_change: bool = False,
) -> InfoItem:
    """Link ``pm_org_id`` to the item, or unlink it when ``None``.

    Raises:
        InfoItemNotFoundError: no such item; Power Map is not asked.
        PowerMapNotConfiguredError, PowerMapUnavailableError, OrgNotFoundError:
            from ``fetch_linkable_org``; nothing is written.
        OrgUnnamedError: the org has no canonical name to supply ``org.title``.
        RepFieldsRefusedError: the new effective bag breaks an active assignment.
        RepFieldsMoveError: it moves an active assignment's path and
            ``allow_destination_change`` is false.
    """
    if await db.get(InfoItem, info_item_id) is None:
        raise InfoItemNotFoundError(str(info_item_id))
    fetched = await fetch_linkable_org(power_map, pm_org_id) if pm_org_id is not None else None

    item = await lock_info_item(db, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    old_org = await load_org_values(db, item)
    old_bag = item.rep_fields or {}
    if fetched is not None:
        row = await apply_org_snapshot(db, fetched, now=datetime.now(UTC))
        new_pm_org_id, new_org = row.pm_org_id, org_values(row)
        new_bag = without_org_owned_keys(old_bag)
    else:
        new_pm_org_id, new_org = None, None
        new_bag = with_org_values(old_bag, old_org)

    assignments = await active_assignments(db, info_item_id)
    refusals = assignment_refusals(assignments, new_bag, org=new_org)
    if refusals:
        raise RepFieldsRefusedError(refusals)
    moves = destination_moves(assignments, old_bag, new_bag, old_org=old_org, new_org=new_org)
    if moves and not allow_destination_change:
        raise RepFieldsMoveError(moves)

    previous = item.pm_org_id
    item.pm_org_id = new_pm_org_id
    item.rep_fields = new_bag
    await db.flush()
    log_moves("Power Map org link moved assignment destinations", info_item_id, moves)
    if previous != new_pm_org_id:
        logger.info(
            "Power Map org linked" if new_pm_org_id else "Power Map org unlinked",
            extra={
                "info_item_id": str(info_item_id),
                "pm_org_id": new_pm_org_id,
                "previous_pm_org_id": previous,
            },
        )
    return item
