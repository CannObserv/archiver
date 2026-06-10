from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.watched_item_template_response_content_config_type_0 import (
        WatchedItemTemplateResponseContentConfigType0,
    )


T = TypeVar("T", bound="WatchedItemTemplateResponse")


@_attrs_define
class WatchedItemTemplateResponse:
    """Single notification template under a WatchedItem.

    Attributes:
        id (str):
        watched_item_id (str):
        title (None | str):
        channel_hint (str):
        events (list[str]):
        is_active (bool):
        content_config (None | WatchedItemTemplateResponseContentConfigType0):
        remote_channel_id (None | str):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
    """

    id: str
    watched_item_id: str
    title: None | str
    channel_hint: str
    events: list[str]
    is_active: bool
    content_config: None | WatchedItemTemplateResponseContentConfigType0
    remote_channel_id: None | str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.watched_item_template_response_content_config_type_0 import (
            WatchedItemTemplateResponseContentConfigType0,
        )

        id = self.id

        watched_item_id = self.watched_item_id

        title: None | str
        title = self.title

        channel_hint = self.channel_hint

        events = self.events

        is_active = self.is_active

        content_config: dict[str, Any] | None
        if isinstance(self.content_config, WatchedItemTemplateResponseContentConfigType0):
            content_config = self.content_config.to_dict()
        else:
            content_config = self.content_config

        remote_channel_id: None | str
        remote_channel_id = self.remote_channel_id

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "watched_item_id": watched_item_id,
                "title": title,
                "channel_hint": channel_hint,
                "events": events,
                "is_active": is_active,
                "content_config": content_config,
                "remote_channel_id": remote_channel_id,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.watched_item_template_response_content_config_type_0 import (
            WatchedItemTemplateResponseContentConfigType0,
        )

        d = dict(src_dict)
        id = d.pop("id")

        watched_item_id = d.pop("watched_item_id")

        def _parse_title(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        title = _parse_title(d.pop("title"))

        channel_hint = d.pop("channel_hint")

        events = cast(list[str], d.pop("events"))

        is_active = d.pop("is_active")

        def _parse_content_config(
            data: object,
        ) -> None | WatchedItemTemplateResponseContentConfigType0:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                content_config_type_0 = WatchedItemTemplateResponseContentConfigType0.from_dict(
                    data
                )

                return content_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | WatchedItemTemplateResponseContentConfigType0, data)

        content_config = _parse_content_config(d.pop("content_config"))

        def _parse_remote_channel_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        remote_channel_id = _parse_remote_channel_id(d.pop("remote_channel_id"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        watched_item_template_response = cls(
            id=id,
            watched_item_id=watched_item_id,
            title=title,
            channel_hint=channel_hint,
            events=events,
            is_active=is_active,
            content_config=content_config,
            remote_channel_id=remote_channel_id,
            created_at=created_at,
            updated_at=updated_at,
        )

        watched_item_template_response.additional_properties = d
        return watched_item_template_response

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
