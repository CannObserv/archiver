"""InfoItem ↔ InfoSource binding (operator-declared).

Role semantics:
- ``NULL`` — root-shaped binding. Two states:
  - *Current primary*: ``deactivated_at IS NULL``. One per InfoItem (partial-unique index).
    Its InfoSource URL is fetched by Watcher each tick.
  - *Previous primary*: ``deactivated_at IS NOT NULL``. Retained as succession history.
    Watcher may continue watching these for unanticipated changes.
- ``'cross_check'`` — fragment-shaped binding; selector extracts the same
  content as current primary via a different selector. Used at fetch time to
  detect selector rot.
- ``'sub_aspect'`` — fragment-shaped binding; selector extracts a different
  content area of the same fetched page. Operator-watchable from Watcher.

Fragment bindings do not auto-transfer when the primary is replaced; each
remains anchored to the InfoSource it was bound against.

Shape consistency (NULL ↔ root, role ↔ fragment) and fragment-shares-root
are enforced in the app layer (``src/core/tools/bind_info_source.py``),
not the DB. The DB only enforces the role enum and the active-root
uniqueness constraint.
"""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType

# Allowed non-null role values. NULL is the implicit "primary" role.
FRAGMENT_ROLES: tuple[str, ...] = ("cross_check", "sub_aspect")
FragmentRole = Literal["cross_check", "sub_aspect"]


class InfoItemSource(Base):
    """Operator-declared binding between an InfoItem and an InfoSource."""

    __tablename__ = "info_item_sources"

    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id"),
        primary_key=True,
    )
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "role IS NULL OR role IN ('cross_check', 'sub_aspect')",
            name="ck_info_item_sources_role_values",
        ),
        Index(
            "uq_info_item_sources_active_root",
            "info_item_id",
            unique=True,
            postgresql_where=text("deactivated_at IS NULL AND role IS NULL"),
        ),
        {"schema": "information"},
    )
