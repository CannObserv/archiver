"""Changes outbox — pending change-bus events drained by the publisher background task."""

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class ChangesOutboxRow(Base):
    """A single pending event waiting to be published to the change bus."""

    __tablename__ = "changes_outbox"

    id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bus_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publish_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_changes_outbox_unpublished_created",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
        {"schema": "information"},
    )
