"""WatchCheckCommand — one check-now click, and what became of it (archiver#370 D2)."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType


class WatchCheckCommand(Base):
    """The issuer's record of one ``info.watch-check`` command.

    Written in the transaction that outboxes the command, so a row means a
    command is on its way. The check-now block's state derives from the item's
    latest row plus ``watch_status`` (``src.core.services.watch_check``):

    - ``rejected_reason`` set → **rejected**, the reason verbatim (Watcher's
      vocabulary is closed on its side and open here);
    - ``watch_status.last_full_fetch_at`` past ``requested_at`` → **done**;
    - older than the timeout → **no answer yet**;
    - else **pending**.

    Nothing records success: success is a level on ``info.watch-status``, read
    at render time. ``rejected_*`` is the only outcome stored, written once by
    the ``check_rejected`` fact (first write wins).

    ``requested_at`` is Archiver's clock, stamped at the outbox write; Watcher's
    ``last_full_fetch_at`` is compared against it across two VMs, with no slack.
    """

    __tablename__ = "watch_check_commands"

    command_id: Mapped[str] = mapped_column(Text, primary_key=True)
    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """The wire's ``requested_at``: a fetch must postdate it to complete the check."""
    requested_by: Mapped[ULID | None] = mapped_column(
        ULIDType(),
        ForeignKey("information.app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The operator who clicked. An id, not an email: this table stays readable
    to the production read role (archiver#348) without a column allowlist."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    """``CheckRejectedEvent.reason``, verbatim. Opaque: an unknown token renders as is."""
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """The fact's ``occurred_at`` (Watcher's clock)."""

    __table_args__ = (
        # "The item's latest command": the block's one read per render.
        Index("ix_watch_check_commands_item_requested", "info_item_id", "requested_at"),
        {"schema": "information"},
    )
