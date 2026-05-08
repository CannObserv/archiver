"""InfoItem ↔ SourceRevision binding (append-only)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType


class InfoItemSourceRevision(Base):
    """Append-only history of which revisions an item has bound to."""

    __tablename__ = "info_item_source_revisions"

    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_revision_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.source_revisions.source_revision_id"),
        primary_key=True,
    )
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_iisr_item_bound_desc",
            "info_item_id",
            "bound_at",
        ),
        {"schema": "information"},
    )
