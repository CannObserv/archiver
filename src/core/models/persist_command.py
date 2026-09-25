"""PersistCommand — one ``content.persist`` occasion, and what became of it."""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType


class PersistCommand(Base):
    """The issuer's durable record of one persist occasion (archiver#276).

    ``ReplicationCommand``'s shape, for ``replicate``'s reasons: MUST-2's
    ``command_id`` mapping must be durable before the XADD, open commands are a
    query rather than an inference, and a dashboard needs a state.

    **The only link from an outcome back to the registry.** ``blob_persisted`` and
    ``persist_failed`` carry no ``source_revision_id`` or ``info_source_id``, by
    design (cannobserv#493): the stored object belongs to its digest, shared by
    every revision whose raw bytes hash to it. ``source_revision_id`` here records
    which revision *occasioned* the command, not who owns the object; a success
    stamps ``persisted_at`` on every revision carrying ``content_fingerprint``.

    ``content_fingerprint`` is the **raw-bytes** sha256, bare hex, the wire name
    ``ContentPersistCommand`` uses. It is ``source_revisions.blob_fingerprint``,
    never ``source_revisions.content_fingerprint`` (the extracted one).
    """

    __tablename__ = "persist_commands"

    command_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_revision_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.source_revisions.source_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )

    # What was sent.
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    blob_uri: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    # Lifecycle. ``requested`` → ``persisted`` | ``failed`` | ``abandoned``.
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Replicator's producer-owned failure token, or a local one
    (``digest_mismatch``). Opaque: branching on it would make every new token a
    code change."""
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """The stored object's size, from ``blob_persisted``."""
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """``occurred_at`` of the newest outcome fact applied, the same ordering guard
    ``ReplicationCommand.last_fact_at`` is. It orders the *command's* state only;
    ``persisted_at`` on the revisions is a minimum over every success fact."""

    __table_args__ = (
        # Enforced in the database for replication_commands' reason (its CR #13):
        # the open index below hard-codes ``state = 'requested'``.
        CheckConstraint(
            "state IN ('requested', 'persisted', 'failed', 'abandoned')",
            name="ck_persist_commands_state",
        ),
        Index(
            "ix_persist_commands_open",
            "issued_at",
            postgresql_where=text("closed_at IS NULL AND state = 'requested'"),
        ),
        Index("ix_persist_commands_revision", "source_revision_id"),
        Index("ix_persist_commands_fingerprint", "content_fingerprint"),
        {"schema": "information"},
    )
