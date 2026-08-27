"""Changes outbox - pending change-bus events drained by the publisher background task."""

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

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bus_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Failure counter only - the publisher increments this on a failed XADD,
    # not on success. A successfully-published row has publish_attempts == 0.
    publish_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Terminal state for a deterministically-unpublishable (poison) row - an
    # unknown event_type / unvalidatable payload, or a persistent failure past the
    # attempt ceiling. Set → the drain loop stops selecting it, ending the
    # infinite-retry + log-spam loop (archiver#107). last_error/payload are kept
    # in-row for post-mortem. NULL = live (never dead-lettered).
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Partial index over the drain loop's exact predicate: a row is a
        # publish candidate only while both published_at and dead_lettered_at
        # are NULL.
        Index(
            "ix_changes_outbox_unpublished_created",
            "created_at",
            postgresql_where=text("published_at IS NULL AND dead_lettered_at IS NULL"),
        ),
        # Tiny partial index (poison rows only) backing the dead_lettered_count
        # observability query (archiver#112) - the table has no pruner, so a
        # bare COUNT over it degrades to an ever-slower seq scan.
        Index(
            "ix_changes_outbox_dead_lettered",
            "dead_lettered_at",
            postgresql_where=text("dead_lettered_at IS NOT NULL"),
        ),
        {"schema": "information"},
    )
