"""PmOrganization — the local snapshot of one linked Power Map org (archiver#304)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class PmOrganization(Base):
    """A Power Map org as archiver last saw it: the source of ``org.title``/``org.acronym``.

    Written only by the link and the follower (archiver#305), never edited in
    archiver. Rendering reads this row and never Power Map itself, which is what
    keeps Power Map off the replication path. Items point here through
    ``info_items.pm_org_id``; a row is kept while any item does (``RESTRICT``),
    and kept after a merge for provenance (``merged_into``).
    """

    __tablename__ = "pm_organizations"
    __table_args__ = {"schema": "information"}

    pm_org_id: Mapped[str] = mapped_column(Text, primary_key=True)
    """Power Map's org id (a ULID, held as Power Map spells it)."""
    name: Mapped[str] = mapped_column(Text, nullable=False)
    """Canonical name at the last check: the effective bag's ``org.title``."""
    acronym: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Canonical acronym at the last check: ``org.acronym``, absent when ``NULL``."""
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    succeeded_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    """A re-key names a *different* org: a notice, never followed."""
    merged_into: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Set on the loser of a merge; its items are re-pointed at the winner."""
    renamed_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The previous canonical name, when a refresh saw ``name`` change."""
    renamed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The last 200's ETag, sent back as ``If-None-Match``."""
    pm_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Power Map's ``updated_at`` for the org."""
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """When archiver last got an answer about this org."""
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """First check that found the org gone; the last snapshot keeps rendering."""
