from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..models.notification_subscription_out_events_item import NotificationSubscriptionOutEventsItem
from ..models.notification_subscription_out_scope import NotificationSubscriptionOutScope

if TYPE_CHECKING:
    from ..models.notification_subscription_out_content_config_type_0 import (
        NotificationSubscriptionOutContentConfigType0,
    )


T = TypeVar("T", bound="NotificationSubscriptionOut")


@_attrs_define
class NotificationSubscriptionOut:
    """One notification subscription.

    Attributes:
        content_config (None | NotificationSubscriptionOutContentConfigType0): As stored: the ContentConfig sent,
            without the defaults it omitted. null = all defaults.
        created_at (datetime.datetime):
        domain (None | str): The Domain's hostname, for domain scope.
        domain_id (None | str):
        events (list[NotificationSubscriptionOutEventsItem]):
        id (str):
        imported_watcher_id (None | str):
        info_item_id (None | str):
        is_active (bool):
        remote_channel_id (str):
        scope (NotificationSubscriptionOutScope):
        title (str):
        updated_at (datetime.datetime):
    """

    content_config: None | NotificationSubscriptionOutContentConfigType0
    created_at: datetime.datetime
    domain: None | str
    domain_id: None | str
    events: list[NotificationSubscriptionOutEventsItem]
    id: str
    imported_watcher_id: None | str
    info_item_id: None | str
    is_active: bool
    remote_channel_id: str
    scope: NotificationSubscriptionOutScope
    title: str
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.notification_subscription_out_content_config_type_0 import (
            NotificationSubscriptionOutContentConfigType0,
        )

        content_config: dict[str, Any] | None
        if isinstance(self.content_config, NotificationSubscriptionOutContentConfigType0):
            content_config = self.content_config.to_dict()
        else:
            content_config = self.content_config

        created_at = self.created_at.isoformat()

        domain: None | str
        domain = self.domain

        domain_id: None | str
        domain_id = self.domain_id

        events = []
        for events_item_data in self.events:
            events_item = events_item_data.value
            events.append(events_item)

        id = self.id

        imported_watcher_id: None | str
        imported_watcher_id = self.imported_watcher_id

        info_item_id: None | str
        info_item_id = self.info_item_id

        is_active = self.is_active

        remote_channel_id = self.remote_channel_id

        scope = self.scope.value

        title = self.title

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "content_config": content_config,
                "created_at": created_at,
                "domain": domain,
                "domain_id": domain_id,
                "events": events,
                "id": id,
                "imported_watcher_id": imported_watcher_id,
                "info_item_id": info_item_id,
                "is_active": is_active,
                "remote_channel_id": remote_channel_id,
                "scope": scope,
                "title": title,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.notification_subscription_out_content_config_type_0 import (
            NotificationSubscriptionOutContentConfigType0,
        )

        d = dict(src_dict)

        def _parse_content_config(
            data: object,
        ) -> None | NotificationSubscriptionOutContentConfigType0:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                content_config_type_0 = NotificationSubscriptionOutContentConfigType0.from_dict(
                    data
                )

                return content_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | NotificationSubscriptionOutContentConfigType0, data)

        content_config = _parse_content_config(d.pop("content_config"))

        created_at = isoparse(d.pop("created_at"))

        def _parse_domain(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        domain = _parse_domain(d.pop("domain"))

        def _parse_domain_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        domain_id = _parse_domain_id(d.pop("domain_id"))

        events = []
        _events = d.pop("events")
        for events_item_data in _events:
            events_item = NotificationSubscriptionOutEventsItem(events_item_data)

            events.append(events_item)

        id = d.pop("id")

        def _parse_imported_watcher_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        imported_watcher_id = _parse_imported_watcher_id(d.pop("imported_watcher_id"))

        def _parse_info_item_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        info_item_id = _parse_info_item_id(d.pop("info_item_id"))

        is_active = d.pop("is_active")

        remote_channel_id = d.pop("remote_channel_id")

        scope = NotificationSubscriptionOutScope(d.pop("scope"))

        title = d.pop("title")

        updated_at = isoparse(d.pop("updated_at"))

        notification_subscription_out = cls(
            content_config=content_config,
            created_at=created_at,
            domain=domain,
            domain_id=domain_id,
            events=events,
            id=id,
            imported_watcher_id=imported_watcher_id,
            info_item_id=info_item_id,
            is_active=is_active,
            remote_channel_id=remote_channel_id,
            scope=scope,
            title=title,
            updated_at=updated_at,
        )

        notification_subscription_out.additional_properties = d
        return notification_subscription_out

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
