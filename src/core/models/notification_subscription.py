"""NotificationSubscription — who hears which events, and how (archiver#363, D1).

Replaces Watcher's ``notification_templates`` (design D3: Archiver decides who
hears). A subscription has one **scope**: ``global`` (every item), ``domain``
(items whose announcing source's host is that Domain row's ``name``) or
``item`` (one InfoItem). The scopes are a union; ``subscriptions_for`` in
``src.core.services.notification_subscriptions`` is the one matcher.

**The scope and its ref are immutable** (Watcher's rule): re-scoping is delete
and create. The Domain ref is ``RESTRICT``, not Watcher's ``CASCADE``: a Domain
delete refuses (409) while a subscription names it, as it does while an
InfoSource does. The item ref cascades, like every child of an item.

``content_config`` is Watcher's ``ContentConfig`` as sent (``NULL``: all
defaults), validated at write time by ``src.api.schemas.notification_subscription``.
``imported_watcher_id`` is the importer's key (D6): a re-run lands on the same
subscription, never a new one. Nothing here sends: dispatch is #369.
"""

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, TimestampMixin, ULIDType, generate_ulid

NOTIFICATION_EVENTS = ("change_detected", "watch_error", "watch_recovered")
"""Watcher's ``WatchEventType``, in its declaration order (the form's order too)."""

SCOPES = ("global", "domain", "item")

_ULID_PATTERN = "^[0-9A-HJKMNP-TV-Z]{26}$"


class NotificationSubscription(Base, TimestampMixin):
    """One subscription: a scope, an event set, content options and a Notifier channel."""

    __tablename__ = "notification_subscriptions"

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    domain_id: Mapped[ULID | None] = mapped_column(
        ULIDType(),
        ForeignKey("information.domains.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    """Set iff ``scope = 'domain'``."""
    info_item_id: Mapped[ULID | None] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """Set iff ``scope = 'item'``."""
    events: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    # none_as_null: "all defaults" persists as SQL NULL, not the JSONB 'null'.
    content_config: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    remote_channel_id: Mapped[str] = mapped_column(String(26), nullable=False)
    """A Notifier channel in Archiver's tenant. Shape only until #368 can look it up."""
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    imported_watcher_id: Mapped[ULID | None] = mapped_column(ULIDType(), nullable=True)
    """The Watcher template this was imported from; set on create only."""

    __table_args__ = (
        CheckConstraint(
            "(scope = 'global' AND domain_id IS NULL AND info_item_id IS NULL)"
            " OR (scope = 'domain' AND domain_id IS NOT NULL AND info_item_id IS NULL)"
            " OR (scope = 'item' AND info_item_id IS NOT NULL AND domain_id IS NULL)",
            name="ck_notification_subscriptions_scope",
        ),
        CheckConstraint(
            "cardinality(events) > 0 AND events <@ ARRAY["
            + ", ".join(f"'{e}'" for e in NOTIFICATION_EVENTS)
            + "]::varchar[]",
            name="ck_notification_subscriptions_events",
        ),
        CheckConstraint(
            f"remote_channel_id ~ '{_ULID_PATTERN}'",
            name="ck_notification_subscriptions_channel",
        ),
        UniqueConstraint(
            "imported_watcher_id", name="uq_notification_subscriptions_imported_watcher_id"
        ),
        {"schema": "information"},
    )

    def __init__(self, **kwargs):
        """Default ``is_active`` on a transient object too, as the DB does."""
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)
