"""Replication specification — provider config + path template + required fields."""

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class RepSpec(Base):
    """A replication specification for a particular provider."""

    __tablename__ = "rep_specs"

    rep_spec_id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    # Nullable, never defaulted: NULL means "never edited". Defaulting to
    # created_at would assert an edit that did not happen. Stamped by
    # src/core/tools/update_rep_spec.py, and only when a field actually changes.
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    __table_args__ = (
        Index("ix_rep_specs_provider", "provider"),
        Index("ix_rep_specs_created_at_id", "created_at", "rep_spec_id"),
        {"schema": "information"},
    )
