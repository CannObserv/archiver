"""Local cache of ``info.watch-status`` — Watcher's reported scheduler state.

One row per InfoItem, last-write-wins in stream order (archiver#151). The
watched-item panel renders from this table instead of a synchronous SDK call;
a stale or absent row degrades the panel and must never fail a mutation, a
route, or a publish.

Every value here is **reported by Watcher, not locally verified** — if Watcher
stamps it wrongly, the cache records it wrongly. The producer coalesces
publishes, so timestamps under-report by up to the republish period (the safe
direction: the registry never claims content is fresher than it is).

A ``revoked`` status message deletes the row rather than marking it: the item
is gone from Watcher's scheduler, and "no row" already renders as the panel's
"no status yet" state. A live message arriving later in the stream legitimately
recreates it (re-announcement at a higher generation).
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType


class WatchStatus(Base, TimestampMixin):
    """Watcher's last reported scheduler state for one InfoItem."""

    __tablename__ = "watch_status"

    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    applied_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """The ``info.registry`` generation Watcher has *applied* — the drift
    detector's second operand, compared against
    ``info_items.announcement_generation`` (the first)."""
    applied_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    """What the scheduler is actually doing. ``False`` is a legitimate value
    (deliberately paused), not absence; ``None`` only ever arrives on a
    tombstone, which deletes the row instead of persisting."""
    applied_interval: Mapped[str | None] = mapped_column(String(20), nullable=True)
    """The cadence actually in use. ``None`` means Watcher's own default is in
    force — a reportable state, not a missing value. Next-due derives from this
    where present, falling back to the announced ``watch_spec`` interval."""
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    health: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """Open vocabulary — ``"ok"`` is the only value that means healthy; every
    other value, known or unknown, is non-healthy and renders verbatim. Never
    test ``health != "error"``."""
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Watcher's publish-time stamp on the message that last wrote this row."""

    __table_args__ = ({"schema": "information"},)


class BusTailCursor(Base):
    """Resume point for a groupless tail consumer — one row per stream.

    A tail reader has no consumer group and therefore no server-side delivery
    cursor; without this, every boot replays the stream from ``0-0``. The
    cursor advances in the same transaction as the write it covers, so a crash
    between the two is impossible and redelivery on restart re-applies an
    idempotent LWW upsert.
    """

    __tablename__ = "bus_tail_cursors"

    stream: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_id: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = ({"schema": "information"},)
