"""Domain — minimal registry of known hostnames."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType, generate_ulid


class Domain(Base, TimestampMixin):
    """Known hostname with lifecycle state and operator notes.

    ``name`` is the hostname (e.g. ``regulations.cannabis.ca.gov``). Unique.
    Rate-limiter columns (min_interval, max_concurrency, etc.) are Watcher-owned
    and intentionally absent here.
    """

    __tablename__ = "domains"

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("name", name="uq_domains_name"),
        {"schema": "information"},
    )
