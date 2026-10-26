"""Deletion record for Domains: the fetch-policy full set's tombstones (archiver#366).

``content.fetch-policy`` is last-write-wins with no delete. Revoking a deleted
host means a ``revoked=True`` frame, and that frame must keep appearing in
**every** full set: drop it and trimming ages it out, after which a booting
consumer replays a stale live value it can no longer revoke (co-core
``FetchPolicyState`` rule 2). The ``Domain`` row is gone, so this table carries
the obligation. Watcher's ``fetch_policy_tombstones``, plus ``generation``: the
value the delete drew from ``fetch_policy_generation_seq``, so the tombstone is
ordered against the host's earlier frames and a re-add's later ones.

A re-add removes the row in its own transaction (``src.core.services.fetch_policy``).
Bounded by the count of deleted hosts.
"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class FetchPolicyTombstone(Base):
    """A deleted host and the generation its tombstone carries, kept for republish."""

    __tablename__ = "fetch_policy_tombstones"

    host: Mapped[str] = mapped_column(Text, primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = ({"schema": "information"},)
