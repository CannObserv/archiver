"""InfoItem ↔ RepSpec assignment (effective-dated)."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class InfoItemRepSpec(Base):
    """A replication assignment with effective dating + public_url writeback."""

    __tablename__ = "info_item_rep_specs"

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        nullable=False,
    )
    rep_spec_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.rep_specs.rep_spec_id"),
        nullable=False,
    )
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Two active rows for one (item, spec) render one destination, and
        # issuance skips both as destination_collision forever (archiver#301).
        # assign_rep_spec refuses first; this is the backstop. Leading with
        # info_item_id, it also serves every item-only active lookup, so it is
        # the table's one active-row index (archiver#311).
        Index(
            "uq_iirs_item_spec_active",
            "info_item_id",
            "rep_spec_id",
            unique=True,
            postgresql_where=text("deactivated_at IS NULL"),
        ),
        Index("ix_iirs_rep_spec", "rep_spec_id"),
        {"schema": "information"},
    )
