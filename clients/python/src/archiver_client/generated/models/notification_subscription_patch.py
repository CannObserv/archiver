from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.notification_subscription_patch_events_type_0_item import (
    NotificationSubscriptionPatchEventsType0Item,
)
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.content_config import ContentConfig


T = TypeVar("T", bound="NotificationSubscriptionPatch")


@_attrs_define
class NotificationSubscriptionPatch:
    """Request body for PATCH /notification-subscriptions/{id}.

    Only the fields sent change. ``content_config`` is replaced whole, and
    ``null`` returns it to all defaults. The scope, its ref and
    ``imported_watcher_id`` are refused: re-scope by deleting and creating.

        Attributes:
            content_config (ContentConfig | None | Unset): Watcher's ContentConfig: `default` options plus per-event
                `overrides`. Unknown keys are refused; title_template/body_template must parse as Jinja (syntax only). null =
                all defaults.
            events (list[NotificationSubscriptionPatchEventsType0Item] | None | Unset): Which events this subscription
                hears: change_detected, watch_error, watch_recovered. Stored de-duplicated, in that order.
            is_active (bool | None | Unset):
            remote_channel_id (None | str | Unset):
            title (None | str | Unset):
    """

    content_config: ContentConfig | None | Unset = UNSET
    events: list[NotificationSubscriptionPatchEventsType0Item] | None | Unset = UNSET
    is_active: bool | None | Unset = UNSET
    remote_channel_id: None | str | Unset = UNSET
    title: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.content_config import ContentConfig

        content_config: dict[str, Any] | None | Unset
        if isinstance(self.content_config, Unset):
            content_config = UNSET
        elif isinstance(self.content_config, ContentConfig):
            content_config = self.content_config.to_dict()
        else:
            content_config = self.content_config

        events: list[str] | None | Unset
        if isinstance(self.events, Unset):
            events = UNSET
        elif isinstance(self.events, list):
            events = []
            for events_type_0_item_data in self.events:
                events_type_0_item = events_type_0_item_data.value
                events.append(events_type_0_item)

        else:
            events = self.events

        is_active: bool | None | Unset
        if isinstance(self.is_active, Unset):
            is_active = UNSET
        else:
            is_active = self.is_active

        remote_channel_id: None | str | Unset
        if isinstance(self.remote_channel_id, Unset):
            remote_channel_id = UNSET
        else:
            remote_channel_id = self.remote_channel_id

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if content_config is not UNSET:
            field_dict["content_config"] = content_config
        if events is not UNSET:
            field_dict["events"] = events
        if is_active is not UNSET:
            field_dict["is_active"] = is_active
        if remote_channel_id is not UNSET:
            field_dict["remote_channel_id"] = remote_channel_id
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.content_config import ContentConfig

        d = dict(src_dict)

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

        def _parse_events(
            data: object,
        ) -> list[NotificationSubscriptionPatchEventsType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                events_type_0 = []
                _events_type_0 = data
                for events_type_0_item_data in _events_type_0:
                    events_type_0_item = NotificationSubscriptionPatchEventsType0Item(
                        events_type_0_item_data
                    )

                    events_type_0.append(events_type_0_item)

                return events_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[NotificationSubscriptionPatchEventsType0Item] | None | Unset, data)

        events = _parse_events(d.pop("events", UNSET))

        def _parse_is_active(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_active = _parse_is_active(d.pop("is_active", UNSET))

        def _parse_remote_channel_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        remote_channel_id = _parse_remote_channel_id(d.pop("remote_channel_id", UNSET))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        notification_subscription_patch = cls(
            content_config=content_config,
            events=events,
            is_active=is_active,
            remote_channel_id=remote_channel_id,
            title=title,
        )

        return notification_subscription_patch
