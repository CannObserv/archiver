"""An in-memory Power Map for tests (archiver#304). CI never calls live Power Map.

Duck-types ``src.core.power_map.PowerMapClient``: ``get_org`` and ``search_orgs``
answer from what the test planted, and ``unavailable`` makes both raise the
adapter's typed error, as a timeout or a 5xx would.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from src.core.power_map import (
    Gone,
    Merged,
    NotModified,
    OrgHit,
    OrgResult,
    OrgSnapshot,
    PowerMapUnavailableError,
    Snapshot,
)

WSLCB_ID = "01JPM00000000000000000000A"
WSLCB_NAME = "Washington State Liquor and Cannabis Board"


def org(pm_org_id: str = WSLCB_ID, name: str | None = WSLCB_NAME, **overrides) -> OrgSnapshot:
    """An ``OrgSnapshot`` with WSLCB's values unless overridden."""
    values = {
        "pm_org_id": pm_org_id,
        "name": name,
        "acronym": "WSLCB",
        "archived_at": None,
        "active": True,
        "succeeded_by": None,
        "pm_updated_at": datetime(2026, 9, 30, tzinfo=UTC),
        "etag": '"v1"',
    }
    values.update(overrides)
    return OrgSnapshot(**values)


class FakePowerMap:
    """Planted orgs, merges and an outage switch; records every call."""

    def __init__(self, *orgs: OrgSnapshot) -> None:
        self.orgs: dict[str, OrgSnapshot] = {o.pm_org_id: o for o in orgs}
        self.merged: dict[str, str] = {}
        self.unavailable: PowerMapUnavailableError | None = None
        self.calls: list[tuple] = []

    def plant(self, snapshot: OrgSnapshot) -> None:
        self.orgs[snapshot.pm_org_id] = snapshot

    def rename(self, pm_org_id: str, name: str, **overrides) -> None:
        self.orgs[pm_org_id] = replace(self.orgs[pm_org_id], name=name, **overrides)

    async def get_org(self, pm_org_id: str, etag: str | None = None) -> OrgResult:
        self.calls.append(("get_org", pm_org_id, etag))
        if self.unavailable is not None:
            raise self.unavailable
        if pm_org_id in self.merged:
            return Merged(winner=self.merged[pm_org_id])
        snapshot = self.orgs.get(pm_org_id)
        if snapshot is None:
            return Gone()
        if etag is not None and etag == snapshot.etag:
            return NotModified()
        return Snapshot(org=snapshot)

    async def search_orgs(self, q: str, limit: int = 10) -> list[OrgHit]:
        self.calls.append(("search_orgs", q, limit))
        if self.unavailable is not None:
            raise self.unavailable
        needle = q.lower()
        return [
            OrgHit(
                pm_org_id=o.pm_org_id,
                name=o.name,
                acronym=o.acronym,
                archived_at=o.archived_at,
                succeeded_by=o.succeeded_by,
            )
            for o in self.orgs.values()
            if o.archived_at is None
            and (needle in (o.name or "").lower() or needle in (o.acronym or "").lower())
        ][:limit]
