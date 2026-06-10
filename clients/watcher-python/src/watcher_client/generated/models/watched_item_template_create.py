from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.watched_item_template_create_content_config_type_0 import (
        WatchedItemTemplateCreateContentConfigType0,
    )


T = TypeVar("T", bound="WatchedItemTemplateCreate")


@_attrs_define
class WatchedItemTemplateCreate:
    """Create a notification template under a WatchedItem.

    Attributes:
        channel_hint (str):
        title (None | str | Unset):
        events (list[str] | Unset):
        is_active (bool | Unset):  Default: True.
        content_config (None | Unset | WatchedItemTemplateCreateContentConfigType0):
        remote_channel_id (None | str | Unset):
    """

    channel_hint: str
    title: None | str | Unset = UNSET
    events: list[str] | Unset = UNSET
    is_active: bool | Unset = True
    content_config: None | Unset | WatchedItemTemplateCreateContentConfigType0 = UNSET
    remote_channel_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.watched_item_template_create_content_config_type_0 import (
            WatchedItemTemplateCreateContentConfigType0,
        )

        channel_hint = self.channel_hint

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        events: list[str] | Unset = UNSET
        if not isinstance(self.events, Unset):
            events = self.events

        is_active = self.is_active

        content_config: dict[str, Any] | None | Unset
        if isinstance(self.content_config, Unset):
            content_config = UNSET
        elif isinstance(self.content_config, WatchedItemTemplateCreateContentConfigType0):
            content_config = self.content_config.to_dict()
        else:
            content_config = self.content_config

        remote_channel_id: None | str | Unset
        if isinstance(self.remote_channel_id, Unset):
            remote_channel_id = UNSET
        else:
            remote_channel_id = self.remote_channel_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "channel_hint": channel_hint,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title
        if events is not UNSET:
            field_dict["events"] = events
        if is_active is not UNSET:
            field_dict["is_active"] = is_active
        if content_config is not UNSET:
            field_dict["content_config"] = content_config
        if remote_channel_id is not UNSET:
            field_dict["remote_channel_id"] = remote_channel_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.watched_item_template_create_content_config_type_0 import (
            WatchedItemTemplateCreateContentConfigType0,
        )

        d = dict(src_dict)
        channel_hint = d.pop("channel_hint")

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        events = cast(list[str], d.pop("events", UNSET))

        is_active = d.pop("is_active", UNSET)

        def _parse_content_config(
            data: object,
        ) -> None | Unset | WatchedItemTemplateCreateContentConfigType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                content_config_type_0 = WatchedItemTemplateCreateContentConfigType0.from_dict(data)

                return content_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | WatchedItemTemplateCreateContentConfigType0, data)

        content_config = _parse_content_config(d.pop("content_config", UNSET))

        def _parse_remote_channel_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        remote_channel_id = _parse_remote_channel_id(d.pop("remote_channel_id", UNSET))

        watched_item_template_create = cls(
            channel_hint=channel_hint,
            title=title,
            events=events,
            is_active=is_active,
            content_config=content_config,
            remote_channel_id=remote_channel_id,
        )

        watched_item_template_create.additional_properties = d
        return watched_item_template_create

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
