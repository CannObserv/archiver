"""Domain — the registry's per-host policy: lifecycle, politeness floor, default cadence."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Sequence,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType, generate_ulid

DEFAULT_MIN_INTERVAL_SECONDS = 1.0
"""Watcher's ``DEFAULT_MIN_INTERVAL``, so an imported host and a new one agree."""

FETCH_POLICY_GENERATION_SEQ = Sequence(
    "fetch_policy_generation_seq", schema="information", metadata=Base.metadata
)
"""The one source of ``content.fetch-policy`` generations (archiver#366).

One sequence for every host, never a per-row counter: a hostname is a reusable
natural key, so a counter restarting with a re-added row would land below the
deleted host's tombstone and every consumer would skip the host (co-core
``FetchPolicyState`` obligation 3). Deletes draw from it too
(``FetchPolicyTombstone.generation``).

``CACHE 1`` (Postgres's default) is load-bearing, and pinned by
``test_the_generation_sequence_hands_out_values_one_at_a_time``. With a larger
cache each backend pre-allocates its own block, so a later save on a host could
draw below an earlier one, and consumers would drop the newer frame."""


class Domain(Base, TimestampMixin):
    """Known hostname; Archiver is its sole owner (archiver#360, design D4).

    ``name`` is the hostname (e.g. ``regulations.cannabis.ca.gov``). Unique.

    **Suspension is intent.** ``is_active = false`` or a set ``archived_at``
    suspends the host: every item announced on it resolves ``active = false`` on
    ``info.registry`` (``domain_suspended`` in
    ``src.core.services.registry_announcement``, the one predicate). Watcher's
    host-local ``domain_suspended`` stays there as break-glass.

    **Two dark fields.** Stored and editable, read by nothing yet:

    - ``min_interval_seconds`` — request spacing for the host, in seconds. It
      takes effect when Archiver produces ``content.fetch-policy`` (#366, flip
      F1); until then Watcher's value is live, and the re-import before F1
      overwrites an edit made here.
    - ``default_watch_spec`` — a WatchSpec v1 document carrying ``interval``,
      the domain tier of cadence resolution (#364, flip F2). ``NULL`` is "no
      domain default".

    **``fetch_policy_generation``** orders the host's ``content.fetch-policy``
    frames (#366). Drawn from ``FETCH_POLICY_GENERATION_SEQ`` on insert, and
    redrawn only when the host's frame changes, by
    ``src.core.services.fetch_policy`` - never read-modify-written.

    Per-host fetch headers (#376) and a fetch timeout (#377) get their own
    columns when they come: neither field here is a policy blob to extend.
    """

    __tablename__ = "domains"

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    min_interval_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=DEFAULT_MIN_INTERVAL_SECONDS,
        server_default="1.0",
    )
    fetch_policy_generation: Mapped[int] = mapped_column(
        BigInteger,
        FETCH_POLICY_GENERATION_SEQ,
        nullable=False,
        server_default=FETCH_POLICY_GENERATION_SEQ.next_value(),
    )
    # none_as_null: an unset cadence persists as SQL NULL, not the JSONB 'null'.
    default_watch_spec: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("name", name="uq_domains_name"),
        CheckConstraint(
            "min_interval_seconds >= 0 AND min_interval_seconds < 'Infinity'"
            " AND min_interval_seconds <> 'NaN'",
            name="ck_domains_min_interval_seconds",
        ),
        {"schema": "information"},
    )
