from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.notification_subscription_create_events_item import (
    NotificationSubscriptionCreateEventsItem,
)
from ..models.notification_subscription_create_scope import NotificationSubscriptionCreateScope
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.content_config import ContentConfig


T = TypeVar("T", bound="NotificationSubscriptionCreate")


@_attrs_define
class NotificationSubscriptionCreate:
    """Request body for POST /notification-subscriptions.

    ``scope`` takes exactly its ref: ``domain`` a hostname with a Domain row,
    ``item`` an ``info_item_id``, ``global`` neither. Both are fixed after
    create; re-scope by deleting and creating.

        Attributes:
            events (list[NotificationSubscriptionCreateEventsItem]): Which events this subscription hears: change_detected,
                watch_error, watch_recovered. Stored de-duplicated, in that order.
            remote_channel_id (str): The Notifier channel in Archiver's tenant. Shape-checked only.
            scope (NotificationSubscriptionCreateScope):
            title (str):
            content_config (ContentConfig | None | Unset): Watcher's ContentConfig: `default` options plus per-event
                `overrides`. Unknown keys are refused; title_template/body_template must parse as Jinja (syntax only). null =
                all defaults.
            domain (None | str | Unset): domain scope: the Domain's hostname (it must have a row).
            imported_watcher_id (None | str | Unset): The Watcher template this was imported from (the importer's key);
                unique, and fixed after create.
            info_item_id (None | str | Unset): item scope: the InfoItem.
            is_active (bool | Unset):  Default: True.
    """

    events: list[NotificationSubscriptionCreateEventsItem]
    remote_channel_id: str
    scope: NotificationSubscriptionCreateScope
    title: str
    content_config: ContentConfig | None | Unset = UNSET
    domain: None | str | Unset = UNSET
    imported_watcher_id: None | str | Unset = UNSET
    info_item_id: None | str | Unset = UNSET
    is_active: bool | Unset = True

    def to_dict(self) -> dict[str, Any]:
        from ..models.content_config import ContentConfig

        events = []
        for events_item_data in self.events:
            events_item = events_item_data.value
            events.append(events_item)

        remote_channel_id = self.remote_channel_id

        scope = self.scope.value

        title = self.title

        content_config: dict[str, Any] | None | Unset
        if isinstance(self.content_config, Unset):
            content_config = UNSET
        elif isinstance(self.content_config, ContentConfig):
            content_config = self.content_config.to_dict()
        else:
            content_config = self.content_config

        domain: None | str | Unset
        if isinstance(self.domain, Unset):
            domain = UNSET
        else:
            domain = self.domain

        imported_watcher_id: None | str | Unset
        if isinstance(self.imported_watcher_id, Unset):
            imported_watcher_id = UNSET
        else:
            imported_watcher_id = self.imported_watcher_id

        info_item_id: None | str | Unset
        if isinstance(self.info_item_id, Unset):
            info_item_id = UNSET
        else:
            info_item_id = self.info_item_id

        is_active = self.is_active

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "events": events,
                "remote_channel_id": remote_channel_id,
                "scope": scope,
                "title": title,
            }
        )
        if content_config is not UNSET:
            field_dict["content_config"] = content_config
        if domain is not UNSET:
            field_dict["domain"] = domain
        if imported_watcher_id is not UNSET:
            field_dict["imported_watcher_id"] = imported_watcher_id
        if info_item_id is not UNSET:
            field_dict["info_item_id"] = info_item_id
        if is_active is not UNSET:
            field_dict["is_active"] = is_active

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.content_config import ContentConfig

        d = dict(src_dict)
        events = []
        _events = d.pop("events")
        for events_item_data in _events:
            events_item = NotificationSubscriptionCreateEventsItem(events_item_data)

            events.append(events_item)

        remote_channel_id = d.pop("remote_channel_id")

        scope = NotificationSubscriptionCreateScope(d.pop("scope"))

        title = d.pop("title")

        def _parse_content_config(data: object) -> ContentConfig | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                content_config_type_0 = ContentConfig.from_dict(data)

                return content_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ContentConfig | None | Unset, data)

        content_config = _parse_content_config(d.pop("content_config", UNSET))

        def _parse_domain(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        domain = _parse_domain(d.pop("domain", UNSET))

        def _parse_imported_watcher_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        imported_watcher_id = _parse_imported_watcher_id(d.pop("imported_watcher_id", UNSET))

        def _parse_info_item_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        info_item_id = _parse_info_item_id(d.pop("info_item_id", UNSET))

        is_active = d.pop("is_active", UNSET)

        notification_subscription_create = cls(
            events=events,
            remote_channel_id=remote_channel_id,
            scope=scope,
            title=title,
            content_config=content_config,
            domain=domain,
            imported_watcher_id=imported_watcher_id,
            info_item_id=info_item_id,
            is_active=is_active,
        )

        return notification_subscription_create
