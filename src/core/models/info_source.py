"""Information Source — URL-keyed (root) or parent-keyed (fragment)."""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class InfoSource(Base):
    """An InfoSource — either a root (URL-keyed) or a fragment (parent-keyed)."""

    __tablename__ = "info_sources"

    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    parent_info_source_id: Mapped[ULID | None] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_spec: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str | None] = mapped_column(
        Text,
        Computed("(source_spec->'target'->>'url')", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(parent_info_source_id IS NULL) != (url IS NULL)",
            name="ck_info_sources_root_xor_fragment",
        ),
        UniqueConstraint("url", name="uq_info_sources_url"),
        Index(
            "ix_info_sources_parent_created",
            "parent_info_source_id",
            "created_at",
            "info_source_id",
            postgresql_where="parent_info_source_id IS NOT NULL",
        ),
        {"schema": "information"},
    )
