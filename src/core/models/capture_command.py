"""CaptureCommand — one ``content.capture`` occasion, and what became of it."""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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

from src.core.models.base import Base, ULIDType


class CaptureCommand(Base):
    """The issuer's durable record of one viewport capture (archiver#380 slice A).

    ``PersistCommand``'s shape, for its reasons: the ``command_id`` mapping is
    durable before the XADD (written in the outbox transaction), open commands
    are a query rather than an inference, and the dashboard needs a state.
    States ``requested`` → ``stored`` | ``failed`` | ``abandoned``.

    **What was sent** is recorded verbatim (``url``, the viewport, ``full_page``,
    ``wait``): the command carries resolved values only (Replicator's issuer
    contract, C4), so the row is the only record of what was asked.

    **What came back** fills from the first ``capture_stored`` (C1: the first
    success is kept; a redelivery renders again, usually under another digest).
    ``content_fingerprint`` is the stored PNG's sha256, bare hex: **an address,
    never a change signal** - a render varies with fonts, ads and clocks. With
    ``blob_uri`` and ``media_type`` it is a ``content.persist``'s three inputs,
    which slice B sends before ``blob_expires_at``.
    """

    __tablename__ = "capture_commands"

    command_id: Mapped[str] = mapped_column(Text, primary_key=True)
    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id", ondelete="CASCADE"),
        nullable=False,
    )

    # What was sent.
    url: Mapped[str] = mapped_column(Text, nullable=False)
    viewport_width: Mapped[int] = mapped_column(Integer, nullable=False)
    viewport_height: Mapped[int] = mapped_column(Integer, nullable=False)
    full_page: Mapped[bool] = mapped_column(Boolean, nullable=False)
    wait: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    """The wire's ``wait`` as sent; ``None`` captures once ``load`` has fired."""
    requested_by: Mapped[ULID | None] = mapped_column(
        ULIDType(),
        ForeignKey("information.app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The operator who clicked. An id, not an email: readable by the production
    read role (archiver#348) without a column allowlist."""
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    # Lifecycle. ``requested`` → ``stored`` | ``failed`` | ``abandoned``.
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Replicator's producer-owned token, or the reaper's local one. Opaque."""
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """The navigation's HTTP status, from ``capture_failed`` (``http_status``)."""
    terminal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # What came back (``capture_stored``).
    content_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    blob_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blob_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """The temp store's horizon; ``None`` = unknown. A persist must precede it."""
    persisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """The minimum ``blob_persisted`` ``occurred_at`` for ``content_fingerprint``
    (archiver#380 slice B), ``source_revisions.persisted_at``'s rule: set, the
    image is in Replicator's permanent store and ``blob_expires_at`` no longer
    binds."""

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """``occurred_at`` of the newest outcome fact applied: the failure ordering
    guard ``PersistCommand.last_fact_at`` is."""

    __table_args__ = (
        CheckConstraint(
            "state IN ('requested', 'stored', 'failed', 'abandoned')",
            name="ck_capture_commands_state",
        ),
        # The reaper's scan.
        Index(
            "ix_capture_commands_open",
            "issued_at",
            postgresql_where=text("closed_at IS NULL AND state = 'requested'"),
        ),
        # "The source's latest command": the block's one read per render.
        Index("ix_capture_commands_source_issued", "info_source_id", "issued_at"),
        # A persist success stamps every capture carrying its digest (slice B).
        Index("ix_capture_commands_fingerprint", "content_fingerprint"),
        {"schema": "information"},
    )
