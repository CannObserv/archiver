"""Information Source — URL + ordered list of extraction specs."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class InfoSource(Base):
    """An InfoSource — a URL and how to extract content from it.

    ``source_specs`` is a mutable ordered list of extraction specs. The first
    element is the primary strategy; subsequent elements are cross-check
    alternatives for selector-rot detection. All specs must share a content-kind
    family (validated at write time by ``create_info_source`` /
    ``update_info_source_specs``).

    Multiple InfoSources may share the same URL when different InfoItems derive
    distinct semantic content from that URL using different extraction strategies.
    URL is immutable after creation; ``source_specs`` is mutable.
    """

    __tablename__ = "info_sources"

    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_specs: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_info_sources_url", "url"),
        {"schema": "information"},
    )
