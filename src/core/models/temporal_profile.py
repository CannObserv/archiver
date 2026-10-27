"""TemporalProfile — an InfoItem's date-driven cadence and post-action (archiver#365).

Ported from Watcher's ``temporal_profiles`` (design D5, D7): Archiver owns the
intent and executes it, announcing only the resolved interval and ``active``
(placement rule 4). One profile per item: the item's id is the key.

**The current result is persisted** (``resolved_interval``, ``evaluated_on``;
the coordinator brief's D1). Nothing on the announce path reads the clock: the
resolver reads ``resolved_interval``, and only a profile write and the daily
boundary job (``src.core.tools.temporal_boundary``) recompute it. So the hourly
snapshot replays exactly what the last delta said, at that delta's generation.

**``fired_at`` makes the post-action one-shot** (D4), leaving ``is_active`` the
operator's enable switch. Every accepted write clears it (re-arm); a write
whose window has already ended is refused, so a re-arm can never fire twice.

The CHECK constraints hold the shape a hand-edit could break; ``rules`` is
validated in Python (``src.core.services.temporal_evaluation``), and a row that
fails it is skipped by the job with a WARNING, never raised.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType

PROFILE_TYPES = ("event", "seasonal", "deadline")
DATE_PROFILE_TYPES = ("event", "deadline")
POST_ACTIONS = ("reduce_frequency", "deactivate", "archive")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class TemporalProfile(Base, TimestampMixin):
    """One InfoItem's temporal profile, and the result it resolved to last."""

    __tablename__ = "temporal_profiles"

    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    profile_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    """``event`` / ``deadline``: the date the rules count down to."""
    date_range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_range_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    """``seasonal``: the inclusive range. Absolute dates; nothing recurs yearly."""
    rules: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    """``[{"days_before": int, "interval": str}]``; seasonal: one ``{"interval": str}``."""
    post_action: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    resolved_interval: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """The interval the profile contributes as of ``evaluated_on``; ``NULL`` contributes none."""
    evaluated_on: Mapped[date] = mapped_column(Date, nullable=False)
    """The UTC day ``resolved_interval`` was computed for."""
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When the post-action fired; ``NULL`` while it has not."""

    __table_args__ = (
        CheckConstraint(_in("profile_type", PROFILE_TYPES), name="ck_temporal_profiles_type"),
        CheckConstraint(_in("post_action", POST_ACTIONS), name="ck_temporal_profiles_post_action"),
        CheckConstraint(
            f"({_in('profile_type', DATE_PROFILE_TYPES)} AND reference_date IS NOT NULL"
            " AND date_range_start IS NULL AND date_range_end IS NULL)"
            " OR (profile_type = 'seasonal' AND reference_date IS NULL"
            " AND date_range_start IS NOT NULL AND date_range_end IS NOT NULL"
            " AND date_range_start <= date_range_end)",
            name="ck_temporal_profiles_dates",
        ),
        CheckConstraint("jsonb_typeof(rules) = 'array'", name="ck_temporal_profiles_rules"),
        {"schema": "information"},
    )

    def __init__(self, **kwargs):
        """Default ``rules`` and ``is_active`` on a transient object too, as the DB does."""
        kwargs.setdefault("rules", [])
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)
