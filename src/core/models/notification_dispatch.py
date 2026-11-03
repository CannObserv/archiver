"""NotificationDispatch — what a fact made Archiver send, or would have (archiver#369, D1).

One row per (``info.watch-events`` fact, matching subscription), composed at
consume time, plus one per error reminder (D5). The table is **both the shadow
log and the dispatch outbox**: ``mode`` says which. A row is ``send`` only when
the cutover instant T is set and the fact's (or reminder's) instant is at or
after it (D3); otherwise it is ``shadow`` and is never sent. Nothing here goes
on ``changes_outbox``, which is the bus outbox.

- **Unique on (``event_id``, ``subscription_id``, ``reminder``)**, so a
  redelivered fact is a no-op. ``reminder`` is 0 for the fact itself and *n* for
  the *n*-th reminder of a ``watch_error`` episode, whose ``event_id`` is the
  episode's edge. ``idempotency_key`` is Notifier's key and unique too.
- **``subscription_id`` is ``SET NULL``**: deleting a subscription keeps the
  history, and its pending rows end ``skipped``, never sent.
- **``info_item_id`` has no FK.** The row records a fact; an item revoked after
  it keeps its history, and its pending send still goes (D2's in-flight rule).
- ``fact`` is the fact as received. A reminder rebuilds its ``WatchErrorEvent``
  from it (``reason``, ``status_code``), and F3's parity export reads it.
"""

from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType, generate_ulid
from src.core.models.notification_subscription import NOTIFICATION_EVENTS

DispatchMode = Literal["shadow", "send"]
DISPATCH_MODES: tuple[str, ...] = get_args(DispatchMode)

DispatchStatus = Literal["shadow", "pending", "sent", "failed", "skipped"]
DISPATCH_STATUSES: tuple[str, ...] = get_args(DispatchStatus)
#: The statuses retention may prune: every one but ``pending``.
TERMINAL_STATUSES: tuple[str, ...] = tuple(s for s in DISPATCH_STATUSES if s != "pending")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class NotificationDispatch(Base, TimestampMixin):
    """One composed notification: shadow-recorded, or queued for Notifier."""

    __tablename__ = "notification_dispatches"

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    """The fact's ``event_id``; for a reminder, its episode's ``watch_error`` edge."""
    reminder: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    """0 for the fact itself; *n* for the *n*-th reminder of its episode (D5)."""
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subscription_id: Mapped[ULID | None] = mapped_column(
        ULIDType(),
        ForeignKey("information.notification_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    info_item_id: Mapped[ULID] = mapped_column(ULIDType(), nullable=False)
    remote_channel_id: Mapped[str] = mapped_column(String(26), nullable=False)
    """The subscription's channel when the row was composed."""
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """The fact's ``occurred_at`` (the episode edge's, on a reminder): F3's parity join key."""
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """A reminder's own instant; set iff ``reminder > 0``."""
    fact: Mapped[dict] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    notifier_dispatch_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why the row is ``failed`` or ``skipped``, or the last retryable error while ``pending``."""
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When a ``pending`` row is next tried; ``NULL`` is now."""

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "subscription_id",
            "reminder",
            name="uq_notification_dispatches_event_subscription_reminder",
        ),
        UniqueConstraint("idempotency_key", name="uq_notification_dispatches_idempotency_key"),
        CheckConstraint(_in("mode", DISPATCH_MODES), name="ck_notification_dispatches_mode"),
        CheckConstraint(_in("status", DISPATCH_STATUSES), name="ck_notification_dispatches_status"),
        CheckConstraint(
            "(mode = 'shadow') = (status = 'shadow')",
            name="ck_notification_dispatches_shadow",
        ),
        CheckConstraint(
            _in("event_type", NOTIFICATION_EVENTS), name="ck_notification_dispatches_event_type"
        ),
        CheckConstraint(
            "reminder >= 0 AND (reminder = 0 OR event_type = 'watch_error')"
            " AND (reminder = 0) = (reminded_at IS NULL)",
            name="ck_notification_dispatches_reminder",
        ),
        # The drain's claim: pending rows, oldest first.
        Index(
            "ix_notification_dispatches_pending",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
        # The reminder timer's episode lookup.
        Index("ix_notification_dispatches_item_occurred", "info_item_id", "occurred_at"),
        # Retention and the log page, newest first.
        Index("ix_notification_dispatches_created_at", "created_at"),
        {"schema": "information"},
    )
