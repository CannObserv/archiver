"""SourceRevision — captured snapshot of an InfoSource at a point in time."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class SourceRevision(Base):
    """A captured snapshot identified by (info_source_id, content_fingerprint)."""

    __tablename__ = "source_revisions"

    source_revision_id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    content_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_cache_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_cache_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "info_source_id",
            "content_fingerprint",
            name="uq_source_revisions_source_fingerprint",
        ),
        Index(
            "ix_source_revisions_source_captured",
            "info_source_id",
            "captured_at",
        ),
        {"schema": "information"},
    )
