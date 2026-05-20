"""App user — authenticated dashboard operator (upserted from exe.dev proxy headers)."""

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType, generate_ulid


class AppUser(Base, TimestampMixin):
    """A human operator authenticated via the exe.dev proxy."""

    __tablename__ = "app_users"

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    external_id: Mapped[str] = mapped_column(Text(), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(Text(), nullable=False, unique=True)

    __table_args__ = ({"schema": "information"},)
