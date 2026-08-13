"""Deletion record for InfoItems — what the snapshot's tombstones are built from.

``revoked: true`` on ``info.registry`` must be republished in **every** full set
(the design's absence-from-snapshot ruling: a consumer whose delta tombstone was
trimmed, and whose snapshots never mention the key, keeps the item forever). The
InfoItem row itself is deleted, so the full-set republish needs a durable record
of what left and at which generation. Same shape and reason as Watcher's
``revoked_info_items`` on the consuming side (watcher#254): every key keeps a
left-hand side for the apply-iff-greater comparison whether or not it still has
a row.

Deliberately no FK to ``info_items`` — the referent is gone by design. Rows are
kept forever; the table grows only with deletions, which are operator-driven and
rare.
"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType


class RevokedInfoItem(Base):
    """A deleted InfoItem's identity + final generation, kept for republish."""

    __tablename__ = "revoked_info_items"

    info_item_id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = ({"schema": "information"},)
