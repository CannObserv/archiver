"""InfoItem ↔ InfoSource binding (operator-declared).

Active binding (``deactivated_at IS NULL``) is the current primary — exactly one
per InfoItem, enforced by ``uq_info_item_sources_active``. Its InfoSource URL is
fetched by Watcher each tick.

Deactivated binding (``deactivated_at IS NOT NULL``) is a previous primary,
preserved indefinitely as succession history.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType


class InfoItemSource(Base):
    """Operator-declared binding between an InfoItem and an InfoSource."""

    __tablename__ = "info_item_sources"

    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_info_item_sources_active",
            "info_item_id",
            unique=True,
            postgresql_where=text("deactivated_at IS NULL"),
        ),
        # The source→item direction (archiver#176). The composite primary key
        # leads with info_item_id, and Postgres has no skip scan, so a lookup by
        # info_source_id alone cannot use it — the domain detail screen would
        # sequentially scan this table twice per render. Partial on the same
        # predicate its only consumer filters by.
        Index(
            "ix_info_item_sources_active_source",
            "info_source_id",
            postgresql_where=text("deactivated_at IS NULL"),
        ),
        {"schema": "information"},
    )
