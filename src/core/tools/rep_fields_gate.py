"""The rep_fields gate — whether one bag can serve one RepSpec (archiver#302).

One check for every writer that pairs a bag with a spec: ``assign_rep_spec``,
the atomic ``POST /info-items`` path, and ``set_rep_fields``. Before #302 the
first two each carried a copy, and the save path had none, which is how a bag
edit could break an assignment that both copies had once approved.

Also the InfoItem row lock those writers share. The race it closes is a
phantom: a save checks the item's active assignments while an assign inserts a
new one, and a row that does not exist yet cannot be locked. Both take the
InfoItem row ``FOR UPDATE`` first, so whichever comes second re-reads the
other's committed state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItem
from src.core.rep_fields import OrgValues
from src.core.rep_fields_schema.validator import (
    ValidationError,
    validate_rep_fields_against_spec,
)
from src.core.replication.destination import probe_destination
from src.core.replication.errors import ReplicationRenderError


@dataclass(frozen=True, slots=True)
class BagCheck:
    """What stops a bag serving a spec; ``ok`` when nothing does.

    ``missing`` holds the shape and ``required_fields`` errors. ``unrenderable``
    is the render failure's reason, and is only looked for once ``missing`` is
    empty: probing a bag that lacks the key restates the miss as a render error.
    """

    missing: list[ValidationError] = field(default_factory=list)
    unrenderable: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the bag satisfies the spec's required fields and renders its path."""
        return not self.missing and self.unrenderable is None


def check_bag_against_spec(
    bag: dict, document: Mapping[str, object], *, org: OrgValues | None
) -> BagCheck:
    """Check ``bag`` against a RepSpec document: required-field presence, then a probe render.

    Both halves read the effective bag, ``bag`` over ``org`` (archiver#303).
    """
    required_fields = document.get("required_fields") or []
    ok, errors = validate_rep_fields_against_spec(bag, list(required_fields), org=org)
    if not ok:
        return BagCheck(missing=errors)
    try:
        probe_destination(document, bag, org=org)
    except ReplicationRenderError as e:
        return BagCheck(unrenderable=str(e))
    return BagCheck()


async def lock_info_item(db: AsyncSession, info_item_id: ULID) -> InfoItem | None:
    """Lock the InfoItem row ``FOR UPDATE`` and return it fresh, or ``None`` if absent.

    ``populate_existing``: an instance already in the session keeps its loaded
    attributes otherwise, and the caller is about to judge the bag it carries.
    """
    return await db.get(InfoItem, info_item_id, with_for_update=True, populate_existing=True)
