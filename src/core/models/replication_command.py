"""ReplicationCommand — one ``content.replicate`` occasion, and what became of it."""

from datetime import UTC, datetime

from sqlalchemy import (
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


class ReplicationCommand(Base):
    """The issuer's durable record of one replication occasion (archiver#169).

    Three jobs, and they are why this is a table rather than a log line:

    - **MUST-2's mapping.** ``command_id → (assignment, revision)`` has to be
      durable *before* the XADD, so a fact arriving for a command the process
      never remembers issuing cannot happen. The row is written in the same
      transaction as the revision insert and the outbox row.
    - **The reaper's queue** (MUST-6). Replicator does not guarantee that every
      command either succeeds or is closed — a provider 5xx retries unbounded
      and publishes no fact at all meanwhile — so "still open past the horizon"
      has to be a query, not an inference.
    - **The dashboard's source** (archiver#171). ``public_url`` acquiring an
      automated writer means the assignment views need a replication state, and
      a *skip* needs one most: a replication that silently did not happen reads
      as "not yet" forever.

    Deliberately not the outbox row. That row is drained, trimmed and
    dead-lettered on a clock unrelated to a command's lifetime, and it is gone
    as a queryable thing once published.

    ``command_id`` is ``Text`` rather than a ULID column even though issuance
    mints ULIDs: it is a wire value that Replicator echoes back verbatim, and the
    consumer (archiver#170) must be able to look up whatever string arrives
    without a parse that can fail. The ULID shape is issuance's choice, not the
    column's contract.
    """

    __tablename__ = "replication_commands"

    command_id: Mapped[str] = mapped_column(Text, primary_key=True)
    info_item_rep_spec_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_item_rep_specs.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The writeback target — the assignment *row*, not (info_item_id,
    rep_spec_id). That pair has no uniqueness, only a partial index over active
    rows, so it stops identifying a target once a spec is deactivated and later
    reassigned."""
    source_revision_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.source_revisions.source_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id", ondelete="RESTRICT"),
        nullable=False,
    )

    # What was sent. Kept even though the RepSpec document is frozen: the
    # assignment's document can be *cloned and migrated* (#95), and the rendered
    # destination is the provenance record archiver#83 found missing — nothing
    # else records which path produced the artifact at a public_url.
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    credentials_alias: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    """NULL only on a skip that never rendered one."""
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    blob_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    # Lifecycle. ``requested`` → ``complete`` | ``failed`` | ``abandoned``
    # (archiver#170 writes the last three); ``skipped`` is terminal on arrival
    # and never had a command on the wire.
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    """A *local* skip reason, or Replicator's producer-owned failure token. Both
    are opaque strings by design — the failure vocabulary belongs to the
    producer, and branching on it here would make every new token a code change."""
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    """From ``replication_failed`` only: False means Replicator is still
    retrying, True means the command is closed. NULL before any failure fact."""
    attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Where the artifact landed, from ``replication_complete``. Mirrored onto
    the assignment row only when this is its newest occasion (R3: the URL is not
    stable across occasions)."""
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """``occurred_at`` of the newest outcome fact applied to this command.

    The ordering guard. ``content.artifacts`` is at-least-once and keyed
    ``command_id:occurred_at`` precisely because one command emits a *sequence*
    of facts, so an out-of-order redelivery is expected traffic — and without a
    recorded high-water mark a stale failure would flip a completed replication
    to ``failed`` while its ``public_url`` still points at a real artifact
    (archiver#170 CR #20/#21). NULL until the first fact arrives; equal
    timestamps are the *same* emission and still apply, since T4 has Replicator
    re-emit a success deliberately."""

    __table_args__ = (
        # The vocabulary, enforced where it is *used* rather than only where it
        # is written. The reaper's partial index below hard-codes
        # ``state = 'requested'``, so a renamed or mistyped state would be
        # written happily and simply stop matching — the reaper would then
        # report an empty queue, which is precisely the silence MUST-6's reaper
        # exists to break (CR #13).
        CheckConstraint(
            "state IN ('requested', 'complete', 'failed', 'abandoned', 'skipped')",
            name="ck_replication_commands_state",
        ),
        # The reaper's exact predicate: still open, oldest first.
        Index(
            "ix_replication_commands_open",
            "issued_at",
            postgresql_where=text("closed_at IS NULL AND state = 'requested'"),
        ),
        # "the newest occasion for this assignment" — the writeback's guard
        # against an older occasion's fact overwriting a newer public_url.
        Index("ix_replication_commands_target", "info_item_rep_spec_id", "issued_at"),
        Index("ix_replication_commands_revision", "source_revision_id"),
        {"schema": "information"},
    )
