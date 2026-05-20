"""API key — per-user hashed key for authenticating /api/v1/* requests."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class ApiKey(Base):
    """A per-user hashed API key. Raw key is shown once at creation and never stored."""

    __tablename__ = "api_keys"

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    user_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(Text(), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    key_hash: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    __table_args__ = ({"schema": "information"},)
