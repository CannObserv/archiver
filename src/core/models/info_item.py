"""Information Item — the stable, externally-named target being tracked."""

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType, generate_ulid
from src.core.watch_spec_schema.validator import DEFAULT_WATCH_SPEC


class InfoItem(Base, TimestampMixin):
    """An Information Item — one specific thing being tracked."""

    __tablename__ = "info_items"

    info_item_id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rep_fields: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
        default=dict,
    )
    watch_spec: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"schema_version": 1, "active": true}',
        default=lambda: dict(DEFAULT_WATCH_SPEC),
    )
    watcher_item_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index(
            "ix_info_items_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_info_items_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        {"schema": "information"},
    )
