"""Information Item — the stable, externally-named target being tracked."""

import json
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType, generate_ulid
from src.core.watch_spec_schema.validator import DEFAULT_WATCH_SPEC


class InfoItem(Base, TimestampMixin):
    """An Information Item — one specific thing being tracked."""

    __tablename__ = "info_items"

    info_item_id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rep_fields: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
        default=dict,
    )
    pm_org_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("information.pm_organizations.pm_org_id", ondelete="RESTRICT"),
        nullable=True,
    )
    """The linked Power Map org (archiver#304), or ``NULL`` when unlinked.

    Its snapshot supplies the effective bag's ``org.title``/``org.acronym``, and
    while it is set the stored bag may not carry either. Written only by
    ``link_org`` and the follower, under the InfoItem row lock.
    """
    watch_spec: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=json.dumps(DEFAULT_WATCH_SPEC),
        default=lambda: dict(DEFAULT_WATCH_SPEC),
    )
    watch_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    """Per-item pause state — deliberately *not* a key in ``watch_spec``.

    ``NULL`` means "the registry has no opinion yet, keep doing what you are
    doing", which is what the one-time Watcher import (archiver#150, since
    retired) filled in. It is a sibling column because a policy *document* shared across
    items could not carry per-item pause state, and because co-core types
    ``active`` on the announcement envelope beside ``revoked`` rather than
    inside the untyped policy dict.
    """
    announcement_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", default=0
    )
    """LWW ordering token for ``info.registry`` (archiver#141).

    Monotonic per item; consumers apply an announcement iff its generation is
    greater than what they hold. Bumped **only** via the atomic
    ``UPDATE … SET announcement_generation = announcement_generation + 1
    RETURNING`` in ``src/core/services/registry_announcement.py`` — never
    read-modify-write in Python, which under concurrency writes N+1 twice and
    makes every consumer discard the second announcement as a duplicate.
    Snapshots read it and never bump it. Default ``0``, not a sentinel: co-core
    rejects negatives because apply-iff-greater would never fire for a key that
    sorted below every legitimate value (cannobserv#302).
    """
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When ``announcement_generation`` last bumped — stamped in the same atomic
    UPDATE (archiver#151).

    The drift detector's clock: "announced gen 9 · applied gen 7 — drift, 40m"
    needs to know *when* gen 9 went out, and ``changes_outbox.published_at`` is
    pruned on a retention window (archiver#189), so the fact lives here. ``NULL``
    until the first bump; snapshots republish without touching it.
    """
    announced_revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    """Whether the last delta announcement was a tombstone (archiver#293).

    Written in the same atomic UPDATE as the bump - ``true`` for a tombstone,
    ``false`` for a live announcement - so it always describes generation
    ``announcement_generation``. The binding path reads it to skip re-tombstoning
    a key that is already revoked: "was live, now isn't" owes a tombstone,
    "was already revoked" does not. Meaningless at generation 0.

    The two ways to be wrong are not symmetric. A stray ``false`` costs one
    redundant tombstone. A stray ``true`` on a live key suppresses the tombstone
    it is owed, and the snapshot cannot repair that: it republishes at the
    generation the consumer already holds live, and apply-iff-greater rejects
    it. Only the announce path may write this column, and code that predates it
    must not run against it (see the v4.22.0 deploy note).
    """

    __table_args__ = (
        Index(
            "ix_info_items_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index("ix_info_items_pm_org_id", "pm_org_id"),
        Index(
            "ix_info_items_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        {"schema": "information"},
    )
