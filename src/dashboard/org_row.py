"""The Overview's Organization row: the linked Power Map org and what to tell about it.

archiver#306. View mode shows the org's name (acronym) and a notice per state
worth an operator's attention; edit mode is a type-ahead whose options come
from ``local_org_options`` (orgs already linked on the item's domains, no Power
Map call) or from Power Map's search (``option_from_hit``).

``build_org_row`` and ``option_from_hit`` are pure: the route loads the
snapshot row, the successor's name and the merge losers. Rendering reads only
``pm_organizations``, never Power Map (CLAUDE.md's edge rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import InfoItem, InfoItemSource, InfoSource, PmOrganization
from src.core.power_map import OrgHit
from src.core.power_map.snapshots import org_values
from src.core.rep_fields import effective_rep_fields

RECENT_DAYS = 30
"""How long a rename or a merge stays news on the row (design §3)."""

LOCAL_OPTIONS_LIMIT = 10


@dataclass(frozen=True, slots=True)
class OrgNotice:
    """One thing to know about the linked org. ``label`` is the badge's word,
    so the state never rides on colour alone; ``level`` picks the badge."""

    kind: str
    label: str
    text: str
    level: str


@dataclass(frozen=True, slots=True)
class OrgRow:
    """The row's view mode: the linked org, or ``linked=False``."""

    linked: bool
    pm_org_id: str | None
    label: str | None
    notices: tuple[OrgNotice, ...]


@dataclass(frozen=True, slots=True)
class OrgOption:
    """One type-ahead choice. ``hint`` is a muted second line, when there is one."""

    pm_org_id: str
    label: str
    hint: str | None


def org_label(name: str | None, acronym: str | None, fallback: str) -> str:
    """``Name (ACRONYM)``, ``Name`` without an acronym, ``fallback`` without a name."""
    if not name:
        return fallback
    return f"{name} ({acronym})" if acronym else name


def build_org_row(
    org: PmOrganization | None,
    *,
    bag: dict,
    now: datetime,
    successor_name: str | None = None,
    merged_from: Sequence[str] = (),
) -> OrgRow:
    """The row for ``org`` (``None``: not linked).

    ``bag`` is the stored bag: the renamed notice states the path the item now
    renders, which a stored ``org.title_slug`` override decides. ``merged_from``
    names the orgs merged into this one within ``RECENT_DAYS``; ``successor_name``
    is ``succeeded_by``'s name when archiver holds a snapshot of it.
    """
    if org is None:
        return OrgRow(linked=False, pm_org_id=None, label=None, notices=())
    recent = now - timedelta(days=RECENT_DAYS)
    notices: list[OrgNotice] = []
    if org.renamed_from and org.renamed_at is not None and org.renamed_at >= recent:
        slug = effective_rep_fields(bag, org_values(org)).get("org", {}).get("title_slug")
        notices.append(
            OrgNotice(
                "renamed",
                "Renamed",
                f"was {org.renamed_from}; paths now organizations/{slug}/…",
                "info",
            )
        )
    for loser in merged_from:
        notices.append(OrgNotice("merged", "Merged", f"{loser} was merged into this org", "info"))
    if org.succeeded_by:
        successor = successor_name or org.succeeded_by
        notices.append(
            OrgNotice(
                "succeeded",
                "Succeeded",
                f"Succeeded by {successor}; relinking is a choice, not automatic",
                "warning",
            )
        )
    if org.archived_at is not None:
        notices.append(OrgNotice("archived", "Archived", "Archived in Power Map", "warning"))
    if not org.active:
        notices.append(OrgNotice("inactive", "Inactive", "Inactive in Power Map", "warning"))
    if org.missing_since is not None:
        notices.append(
            OrgNotice(
                "missing",
                "Missing",
                f"Missing from Power Map since {org.missing_since:%Y-%m-%d}; "
                "the last snapshot still renders",
                "danger",
            )
        )
    return OrgRow(
        linked=True,
        pm_org_id=org.pm_org_id,
        label=org_label(org.name, org.acronym, org.pm_org_id),
        notices=tuple(notices),
    )


def option_from_hit(hit: OrgHit) -> OrgOption:
    """A Power Map search hit as a type-ahead option."""
    return OrgOption(
        pm_org_id=hit.pm_org_id,
        label=org_label(hit.name, hit.acronym, hit.pm_org_id),
        hint="Succeeded by another org in Power Map" if hit.succeeded_by else None,
    )


async def local_org_options(session: AsyncSession, item: InfoItem) -> list[OrgOption]:
    """Orgs already linked to other items on this item's domains, most-linked first.

    What the type-ahead opens with, before a keystroke and without a Power Map
    call. The item's domains are those of its active bindings; its own org is
    left out, since choosing it changes nothing.
    """
    domains = (
        select(InfoSource.domain_name)
        .join(InfoItemSource, InfoItemSource.info_source_id == InfoSource.info_source_id)
        .where(
            InfoItemSource.info_item_id == item.info_item_id,
            InfoItemSource.deactivated_at.is_(None),
            InfoSource.domain_name.is_not(None),
        )
    )
    linked = func.count(func.distinct(InfoItem.info_item_id))
    query = (
        select(PmOrganization, linked)
        .join(InfoItem, InfoItem.pm_org_id == PmOrganization.pm_org_id)
        .join(
            InfoItemSource,
            and_(
                InfoItemSource.info_item_id == InfoItem.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            ),
        )
        .join(InfoSource, InfoSource.info_source_id == InfoItemSource.info_source_id)
        .where(
            InfoSource.domain_name.in_(domains),
            InfoItem.info_item_id != item.info_item_id,
        )
        .group_by(PmOrganization.pm_org_id)
        .order_by(linked.desc(), PmOrganization.name)
        .limit(LOCAL_OPTIONS_LIMIT)
    )
    if item.pm_org_id is not None:
        query = query.where(PmOrganization.pm_org_id != item.pm_org_id)
    rows = await session.execute(query)
    return [
        OrgOption(
            pm_org_id=org.pm_org_id,
            label=org_label(org.name, org.acronym, org.pm_org_id),
            hint=f"Linked to {count} item{'s' if count != 1 else ''} on this domain",
        )
        for org, count in rows
    ]
