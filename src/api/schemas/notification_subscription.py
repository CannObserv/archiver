"""Request/response models for notification subscriptions (archiver#363)."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
)

from src.api.schemas.types import ULIDStr
from src.core.models.notification_subscription import NotificationEvent, Scope
from src.core.notifications.content_config import ContentConfig
from src.core.services.notification_subscriptions import normalize_channel_id

ChannelId = Annotated[str, AfterValidator(normalize_channel_id)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Events = Annotated[list[NotificationEvent], Field(min_length=1)]

_EVENTS_DOC = (
    "Which events this subscription hears: change_detected, watch_error, watch_recovered. "
    "Stored de-duplicated, in that order."
)
_CONTENT_DOC = (
    "Watcher's ContentConfig: `default` options plus per-event `overrides`. Unknown keys "
    "are refused; title_template/body_template must parse as Jinja (syntax only). "
    "null = all defaults."
)


class NotificationSubscriptionCreate(BaseModel):
    """Request body for POST /notification-subscriptions.

    ``scope`` takes exactly its ref: ``domain`` a hostname with a Domain row,
    ``item`` an ``info_item_id``, ``global`` neither. Both are fixed after
    create; re-scope by deleting and creating.
    """

    model_config = {"extra": "forbid"}
    title: Title
    scope: Scope
    domain: str | None = Field(
        default=None, description="domain scope: the Domain's hostname (it must have a row)."
    )
    info_item_id: ULIDStr | None = Field(default=None, description="item scope: the InfoItem.")
    events: Events = Field(description=_EVENTS_DOC)
    remote_channel_id: ChannelId = Field(
        description="The Notifier channel in Archiver's tenant. Shape-checked only."
    )
    is_active: StrictBool = True
    content_config: ContentConfig | None = Field(default=None, description=_CONTENT_DOC)
    imported_watcher_id: ULIDStr | None = Field(
        default=None,
        description="The Watcher template this was imported from (the importer's key); "
        "unique, and fixed after create.",
    )


class NotificationSubscriptionPatch(BaseModel):
    """Request body for PATCH /notification-subscriptions/{id}.

    Only the fields sent change. ``content_config`` is replaced whole, and
    ``null`` returns it to all defaults. The scope, its ref and
    ``imported_watcher_id`` are refused: re-scope by deleting and creating.
    """

    model_config = {"extra": "forbid"}
    title: Title | None = None
    events: Events | None = Field(default=None, description=_EVENTS_DOC)
    remote_channel_id: ChannelId | None = None
    is_active: StrictBool | None = None
    content_config: ContentConfig | None = Field(default=None, description=_CONTENT_DOC)

    @field_validator("title", "events", "remote_channel_id", "is_active", mode="before")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("may not be null; omit the field to leave it unchanged")
        return value


class NotificationSubscriptionOut(BaseModel):
    """One notification subscription."""

    id: str
    title: str
    scope: Scope
    domain_id: str | None
    domain: str | None = Field(description="The Domain's hostname, for domain scope.")
    info_item_id: str | None
    events: list[NotificationEvent]
    content_config: dict[str, Any] | None = Field(
        description="As stored: the ContentConfig sent, without the defaults it omitted. "
        "null = all defaults."
    )
    remote_channel_id: str
    is_active: bool
    imported_watcher_id: str | None
    created_at: datetime
    updated_at: datetime
