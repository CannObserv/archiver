"""SourceRevision — captured snapshot of an InfoSource at a point in time."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class SourceRevision(Base):
    """A captured snapshot identified by (info_source_id, content_fingerprint)."""

    __tablename__ = "source_revisions"

    source_revision_id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_cache_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_cache_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Observation provenance (archiver#139) -------------------------------
    # Carried by SourceRevisionObservedEvent on content.revisions; NULL on rows
    # written through the HTTP authoring/backfill path, which knows none of them.
    #
    # source_media_type is what the *origin* served, as against content_media_type
    # above, which describes the text extracted under source_specs. The two differ
    # for one revision — an HTML page is served text/html and the text extracted
    # from it is not — so neither can stand in for the other. Inherits
    # BlobAvailableEvent.media_type's normalization (charset dropped,
    # application/octet-stream for an absent header), so it cannot express "the
    # origin sent no Content-Type at all".
    source_media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Identifies the source_specs the producer actually extracted under. Recorded
    # and compared, never enforced: archiver#140 makes spec delivery eventually
    # consistent, so extracting under a superseded spec is an expected transient
    # state. Without this column "the origin changed", "our spec changed", and
    # "the producer was behind on announcements" are one indistinguishable new
    # fingerprint.
    spec_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The comparison of spec_fingerprint against this InfoSource's source_specs
    # at ingest, via co-core's shared derivation (cannobserv#309). See
    # src/core/spec_match.py for the vocabulary and why every uncertain branch
    # lands on "incomparable" rather than "superseded".
    #   NULL           no spec_fingerprint was reported — nothing to compare
    #   "current"      matched a spec the registry still holds; see spec_position
    #   "superseded"   THE FLAG: a well-formed value matching none of our specs
    #   "incomparable" unknown derivation or malformed value — never a flag
    spec_match: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which source_specs index the producer extracted under; set only when
    # spec_match is "current". >0 means the primary spec stopped matching and the
    # producer's fallback loop moved on — selector rot in progress.
    spec_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Correlation back to the content.fetch command that produced the bytes — the
    # only provenance link from a registry row to the fetch behind it.
    command_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "info_source_id",
            "content_fingerprint",
            name="uq_source_revisions_source_fingerprint",
        ),
        Index(
            "ix_source_revisions_source_captured",
            "info_source_id",
            "captured_at",
        ),
        {"schema": "information"},
    )
