"""Cadence resolution: the interval ``info.registry`` announces (archiver#364).

Three tiers, highest first: the item's temporal profile, the item's own
``watch_spec.interval``, then its host's ``Domain.default_watch_spec`` (design
C-e). The announcement carries the **resolved** document, never the stored
one: ``{"schema_version": 1, "interval": <winner>}``, or no ``interval`` when no
tier holds one, and Watcher applies its own system default. There is no
Archiver-side system tier (the issue body: "Watcher keeps only a system
default for an absent interval").

``info_items.watch_spec`` stays the item's own intent. Resolving at the
builder rather than on write keeps a domain-default change a fan-out of
announcements instead of a rewrite of every inheriting item's row, and keeps
"inherit" distinguishable from "set to the same value".

**The profile slot is always ``None``** until #365 ports temporal profiles. It
is in the signature now so that #365 changes the resolver, not every caller.

**A malformed tier is skipped, never raised.** Stored documents are validated on
write only, so a hand-edited row (#360's CR 18) reaches here. The resolver runs
on every announce, the hourly snapshot and the panel render: a raise would
dead-letter an announce or 500 a page over one bad cell. The tier is passed
over with a WARNING naming the row, and the next tier decides. The document
built from the winner is valid WatchSpec v1 by construction.
"""

from dataclasses import dataclass
from typing import Literal

from src.core.logging import get_logger
from src.core.models import InfoItem
from src.core.models.domain import Domain
from src.core.watch_spec_schema.validator import validate_domain_watch_spec, validate_watch_spec

logger = get_logger(__name__)

Tier = Literal["profile", "item", "domain"]


@dataclass(frozen=True)
class ResolvedInterval:
    """The winning interval and the tier it came from; ``(None, None)`` defers to Watcher."""

    interval: str | None
    tier: Tier | None

    def watch_spec(self) -> dict:
        """The WatchSpec v1 document ``info.registry`` announces."""
        doc: dict = {"schema_version": 1}
        if self.interval is not None:
            doc["interval"] = self.interval
        return doc


def item_interval(watch_spec: object, *, info_item_id: object) -> str | None:
    """The item tier: its own ``interval``, or ``None`` when absent or malformed."""
    ok, errors = validate_watch_spec(watch_spec)
    if not ok:
        logger.warning(
            "InfoItem watch_spec is malformed; its cadence tier is skipped",
            extra={"info_item_id": str(info_item_id), "errors": errors},
        )
        return None
    return watch_spec.get("interval")


def domain_interval(domain: Domain | None) -> str | None:
    """The domain tier: the host's default ``interval``, or ``None``.

    ``None`` for no row, a ``NULL`` default, or a malformed one (logged).
    """
    if domain is None or domain.default_watch_spec is None:
        return None
    spec = domain.default_watch_spec
    ok, errors = validate_domain_watch_spec(spec)
    if not ok:
        logger.warning(
            "Domain default_watch_spec is malformed; its cadence tier is skipped",
            extra={"domain": domain.name, "errors": errors},
        )
        return None
    return spec["interval"]


def resolve_interval(*, profile: None, item: InfoItem, domain: Domain | None) -> ResolvedInterval:
    """Profile, then item, then domain; the first tier holding an interval wins.

    ``domain`` is the Domain row of the host the item announces on (its active
    binding's source), or ``None`` when the host has no row.
    """
    del profile  # #365: a profile's interval wins over every tier below
    own = item_interval(item.watch_spec, info_item_id=item.info_item_id)
    if own is not None:
        return ResolvedInterval(own, "item")
    inherited = domain_interval(domain)
    if inherited is not None:
        return ResolvedInterval(inherited, "domain")
    return ResolvedInterval(None, None)
